"""Persistence for token disambiguation conflicts (heteronym reading choices
and ambiguous per-kanji furigana splits) surfaced to the user for review.

One row per candidate option, including the default Sudachi already chose
(inserted pre-selected) — resolving is always just moving `selected` to a
different row, which also makes "redo" free: nothing is deleted, so changing
your mind later is another call to `resolve_conflict`.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text

from app.db import json_param
from app.glosses import get_or_create_gloss_lookup, plan_glosses, store_glosses
from app.tokenization import (
    TokenRecord,
    conflict_option_value,
    furigana_spans_for_reading,
    mixed_reading,
    to_hiragana,
    to_katakana,
)


def create_conflicts(conn, document_id: int, records: list[TokenRecord]) -> None:
    """Insert a selected default plus unselected alternatives for every
    flagged record, attached to the document's already-inserted tokens."""
    rows = []
    for record in records:
        if not record.conflict_options:
            continue
        # `reading` below is the inflected surface's own reading (what
        # furigana needs); `citation_reading` is deliberately different —
        # mixed_reading of normalized_form, the citation form's reading,
        # which is what a later gloss lookup is actually keyed by. These
        # differ for an inflected token (揃える's citation reading そろえる
        # vs 揃え's own reading そろえ).
        default_value = conflict_option_value(
            to_hiragana(record.reading_katakana), record.furigana_spans, mixed_reading(record.normalized_form)
        )
        # record.conflict_options never includes this default: heteronym
        # alternatives are built from `[r for r in heteronym_readings(...)
        # if r != reading]`, and no_kana_anchor alternatives are `solutions[1:]`
        # (the chosen split is solutions[0]) — both already exclude the
        # option selected above, so there's no duplicate row here.
        for index, value in enumerate([default_value, *record.conflict_options]):
            rows.append(
                {
                    "position": record.position,
                    "kind": record.review_reason,
                    "value": value,
                    "selected": index == 0,
                    "ord": len(rows),
                }
            )
    if not rows:
        return

    # Ordered, so each token's options get ids in order: the selected
    # default first, then its alternatives.
    conn.execute(
        text(
            """
            INSERT INTO conflicts (token_id, kind, value, selected, selected_at)
            SELECT t.id, c.kind, c.value, c.selected, CASE WHEN c.selected THEN now() END
            FROM jsonb_to_recordset(CAST(:rows AS JSONB))
                AS c(position int, kind text, value jsonb, selected boolean, ord int)
            JOIN tokens t ON t.document_id = :document_id AND t.position = c.position
            ORDER BY c.ord
            """
        ),
        {"document_id": document_id, "rows": json.dumps(rows)},
    )


def _apply_selected_reading(conn, token_id: int, furigana_spans: list[dict], gloss_lookup_id: int) -> None:
    """Write a newly-selected reading's furigana and gloss onto the token
    row itself, for resolve_conflict. (select_reading makes the same update
    to many tokens in one statement.)"""
    conn.execute(
        text(
            """
            UPDATE tokens
            SET furigana_override = CAST(:furigana_spans AS JSONB),
                needs_review = FALSE,
                gloss_lookup_id = :gloss_lookup_id
            WHERE id = :token_id
            """
        ),
        {
            "furigana_spans": json.dumps(furigana_spans),
            "gloss_lookup_id": gloss_lookup_id,
            "token_id": token_id,
        },
    )


class ConflictNotFound(Exception):
    pass


def resolve_conflict(conn, document_id: int, token_id: int, conflict_id: int) -> None:
    # Locks the token row for the rest of this transaction, so a second
    # resolve/correct call for the SAME token (a double-click, or two tabs)
    # blocks until this one commits instead of racing it — both would
    # otherwise read "nothing selected yet" and each insert their own
    # selected=true row, tripping the "one selected row per token" unique
    # index. Concurrent calls for DIFFERENT tokens are unaffected.
    owner = conn.execute(
        text(
            """
            SELECT c.id
            FROM conflicts c
            JOIN tokens t ON t.id = c.token_id
            WHERE c.id = :conflict_id AND c.token_id = :token_id AND t.document_id = :document_id
            FOR UPDATE OF t
            """
        ),
        {"conflict_id": conflict_id, "token_id": token_id, "document_id": document_id},
    ).one_or_none()

    if owner is None:
        raise ConflictNotFound()

    conn.execute(
        text("UPDATE conflicts SET selected = FALSE, selected_at = NULL WHERE token_id = :token_id"),
        {"token_id": token_id},
    )
    conn.execute(
        text("UPDATE conflicts SET selected = TRUE, selected_at = now() WHERE id = :conflict_id"),
        {"conflict_id": conflict_id},
    )

    value = conn.execute(
        text("SELECT value FROM conflicts WHERE id = :conflict_id"),
        {"conflict_id": conflict_id},
    ).scalar_one()

    token = conn.execute(
        text("SELECT normalized_form, dictionary_form FROM tokens WHERE id = :token_id"),
        {"token_id": token_id},
    ).one()

    # Different reading options can be genuinely different words with
    # different glosses (今日 as きょう "today" vs こんにち "these days"), so
    # switching which one is selected has to re-resolve the gloss too, not
    # just the furigana — otherwise the shown gloss goes stale, paired with
    # a reading it no longer matches. citation_reading (not value["reading"])
    # because for an inflected token those differ — value["reading"] is the
    # inflected surface's reading (furigana needs that), citation_reading is
    # what JMDict is actually keyed by. Falls back to "reading" for any
    # conflict row written before this field existed.
    gloss_lookup_id = get_or_create_gloss_lookup(
        conn,
        token.normalized_form,
        value.get("citation_reading", value["reading"]),
        alt_lookup_form=token.dictionary_form,
    )

    _apply_selected_reading(conn, token_id, value["furigana_spans"], gloss_lookup_id)


class TokenNotFound(Exception):
    pass


class TokensNotGroupable(Exception):
    pass


def lock_token_group(
    conn,
    document_id: int,
    token_ids: list[int],
    reading_hiragana: Optional[str] = None,
    furigana_spans: Optional[list[dict]] = None,
) -> list:
    """Lock the document's tokens in `token_ids` (distinct) and return them,
    raising TokenNotFound unless all of them exist, and TokensNotGroupable
    unless they're one word read and parsed the same way with the same
    offered reading options — the only tokens one decision can apply to
    together (groupKey in the frontend mirrors this).

    Given a reading, each returned row's match_id/match_value is the
    token's own option with that reading, if it has one: an offered option
    before a correction, then one split as `furigana_spans`."""
    # Same reason as resolve_conflict's lock: serializes concurrent
    # decisions for any of these tokens rather than letting them race past
    # the "one selected row per token" unique index. In id order, so two
    # requests for overlapping tokens can't deadlock.
    locked = conn.execute(
        text(
            """
            SELECT id FROM tokens
            WHERE document_id = :document_id AND id = ANY(:token_ids)
            ORDER BY id
            FOR UPDATE
            """
        ),
        {"document_id": document_id, "token_ids": token_ids},
    ).all()
    if len(locked) != len(token_ids):
        raise TokenNotFound()

    # Its own statement, not part of the locking one: under READ COMMITTED,
    # only a statement started after the lock was granted sees options the
    # lock's previous holder committed.
    tokens = conn.execute(
        text(
            """
            SELECT t.id, t.surface, t.normalized_form, t.dictionary_form, t.reading_katakana,
                   t.furigana_spans, t.furigana_override,
                   jsonb_build_array(
                       t.surface, t.reading_katakana, t.part_of_speech,
                       COALESCE(
                           (SELECT jsonb_agg(c.value ORDER BY c.id) FROM conflicts c
                            WHERE c.token_id = t.id AND c.kind <> 'custom'),
                           CAST('[]' AS JSONB)
                       )
                   ) AS group_key,
                   EXISTS (SELECT 1 FROM conflicts c WHERE c.token_id = t.id) AS has_options,
                   m.id AS match_id, m.value AS match_value
            FROM tokens t
            LEFT JOIN LATERAL (
                SELECT c.id, c.value
                FROM conflicts c
                WHERE c.token_id = t.id AND c.value ->> 'reading' = :reading
                ORDER BY c.kind = 'custom',
                         c.value -> 'furigana_spans' = CAST(:furigana_spans AS JSONB) DESC NULLS LAST,
                         c.id
                LIMIT 1
            ) m ON TRUE
            WHERE t.id = ANY(:token_ids)
            ORDER BY t.id
            """
        ),
        {"token_ids": token_ids, "reading": reading_hiragana, "furigana_spans": json_param(furigana_spans)},
    ).all()
    if len({json.dumps(t.group_key, sort_keys=True) for t in tokens}) > 1:
        raise TokensNotGroupable()
    return tokens


def select_reading(
    conn,
    document_id: int,
    token_ids: list[int],
    reading_hiragana: str,
    furigana_spans: Optional[list[dict]] = None,
) -> None:
    """Select `reading_hiragana` for each of the document's tokens in
    `token_ids`, which lock_token_group must accept together: the option
    they offer with that reading, if any, preferring one split as
    `furigana_spans`; otherwise each token's own correction to it, added
    the first time, split as `furigana_spans` or by the same alignment as
    automatic tokenization. Nothing is thrown away, so any earlier choice
    can be returned to.

    Also re-resolves each token's gloss under the reading: different
    readings can be different words (今日 as きょう "today" vs こんにち
    "these days"), and a wrong reading is often why a JMDict entry went
    unmatched."""
    tokens = lock_token_group(conn, document_id, token_ids, reading_hiragana, furigana_spans)

    chosen_ids: list[int] = []
    new_rows: list[dict] = []
    selections: list[tuple] = []
    for token in tokens:
        value = token.match_value
        if value is None:
            spans = furigana_spans or furigana_spans_for_reading(token.surface, to_katakana(reading_hiragana))
            # The user's own input is used as-is for citation_reading — for
            # a non-inflected word (the common case for a manual correction)
            # this already is the citation reading; for an inflected one
            # it's the best approximation available without deeper analysis
            # of what they typed.
            value = conflict_option_value(reading_hiragana, spans, reading_hiragana)
            if not token.has_options:
                # First-ever correction for this token: preserve Sudachi's
                # original reading as an unselected row so "redo back to the
                # original" stays possible, as it always is for auto-flagged
                # tokens.
                original = conflict_option_value(
                    to_hiragana(token.reading_katakana),
                    token.furigana_override or token.furigana_spans,
                    mixed_reading(token.normalized_form),
                )
                new_rows.append({"token_id": token.id, "value": original, "selected": False, "ord": len(new_rows)})
            new_rows.append({"token_id": token.id, "value": value, "selected": True, "ord": len(new_rows)})
        else:
            chosen_ids.append(token.match_id)
        selections.append((token, value))

    # citation_reading, not the reading itself, since JMDict is keyed by
    # citation form and the two differ for an inflected token. Falls back to
    # "reading" for any option written before citation_reading existed.
    keys = {token.id: (token.normalized_form, value.get("citation_reading", value["reading"])) for token, value in selections}
    gloss_ids = store_glosses(conn, plan_glosses(conn, [(keys[token.id], token.dictionary_form) for token, _ in selections]))

    # Deselected before anything is selected, for the "one selected row per
    # token" unique index.
    conn.execute(
        text("UPDATE conflicts SET selected = FALSE, selected_at = NULL WHERE token_id = ANY(:token_ids) AND selected"),
        {"token_ids": token_ids},
    )
    if new_rows:
        # Ordered, so a preserved original gets a lower id than the
        # correction that follows it.
        conn.execute(
            text(
                """
                INSERT INTO conflicts (token_id, kind, value, selected, selected_at)
                SELECT token_id, 'custom', value, selected, CASE WHEN selected THEN now() END
                FROM jsonb_to_recordset(CAST(:rows AS JSONB))
                    AS r(token_id int, value jsonb, selected boolean, ord int)
                ORDER BY ord
                """
            ),
            {"rows": json.dumps(new_rows)},
        )
    if chosen_ids:
        conn.execute(
            text("UPDATE conflicts SET selected = TRUE, selected_at = now() WHERE id = ANY(:ids)"),
            {"ids": chosen_ids},
        )
    conn.execute(
        text(
            """
            UPDATE tokens t
            SET furigana_override = v.furigana_spans,
                needs_review = FALSE,
                gloss_lookup_id = v.gloss_lookup_id
            FROM jsonb_to_recordset(CAST(:rows AS JSONB))
                AS v(id int, furigana_spans jsonb, gloss_lookup_id int)
            WHERE t.id = v.id
            """
        ),
        {
            "rows": json.dumps(
                [
                    {"id": token.id, "furigana_spans": value["furigana_spans"], "gloss_lookup_id": gloss_ids[keys[token.id]]}
                    for token, value in selections
                ]
            )
        },
    )


def correct_reading(conn, document_id: int, token_id: int, reading_hiragana: str) -> None:
    """Select a user-supplied pronunciation for a token — for whenever
    Sudachi's own reading is wrong (三股 as みまた instead of さんまた) or
    nothing else offered a fix (no heteronym/split candidates existed, or
    the token is OOV) — as select_reading does."""
    select_reading(conn, document_id, [token_id], reading_hiragana)
