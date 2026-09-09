"""Persistence for token disambiguation conflicts (heteronym reading choices
and ambiguous per-kanji furigana splits) surfaced to the user for review.

One row per candidate option, including the default Sudachi already chose
(inserted pre-selected) — resolving is always just moving `selected` to a
different row, which also makes "redo" free: nothing is deleted, so changing
your mind later is another call to `resolve_conflict`.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.glosses import get_or_create_gloss_lookup
from app.tokenization import TokenRecord, furigana_spans_for_reading, mixed_reading, to_hiragana, to_katakana


def create_conflicts(conn, document_id: int, records: list[TokenRecord]) -> None:
    flagged = [r for r in records if r.conflict_options]
    if not flagged:
        return

    token_ids = dict(
        conn.execute(
            text("SELECT position, id FROM tokens WHERE document_id = :document_id"),
            {"document_id": document_id},
        ).all()
    )

    rows = []
    for record in flagged:
        token_id = token_ids[record.position]
        default_value = {
            "reading": to_hiragana(record.reading_katakana),
            "furigana_spans": record.furigana_spans,
            # Same reading the unflagged default gloss path already uses
            # (mixed_reading(normalized_form)) — for an inflected token
            # this is the citation form's reading (揃える -> そろえる), not
            # record.reading_katakana's inflected-surface reading (揃え ->
            # そろえ), which is what furigana needs but JMDict is not keyed
            # by.
            "citation_reading": mixed_reading(record.normalized_form),
        }
        rows.append(
            {
                "token_id": token_id,
                "kind": record.review_reason,
                "value": json.dumps(default_value),
                "selected": True,
            }
        )
        for option in record.conflict_options:
            rows.append(
                {
                    "token_id": token_id,
                    "kind": record.review_reason,
                    "value": json.dumps(option),
                    "selected": False,
                }
            )

    conn.execute(
        text(
            """
            INSERT INTO conflicts (token_id, kind, value, selected, selected_at)
            VALUES (
                :token_id, :kind, CAST(:value AS JSONB), :selected,
                CASE WHEN :selected THEN now() ELSE NULL END
            )
            """
        ),
        rows,
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
    # conflict row written before this field existed. alt_lookup_form tries
    # dictionary_form's own spelling too — normalized_form isn't always the
    # one JMDict has registered (さり気ない's normalized_form さり気無い isn't
    # JMDict's spelling; dictionary_form さり気ない is).
    gloss_lookup_id = get_or_create_gloss_lookup(
        conn,
        token.normalized_form,
        value.get("citation_reading", value["reading"]),
        alt_lookup_form=token.dictionary_form,
    )

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
            "furigana_spans": json.dumps(value["furigana_spans"]),
            "gloss_lookup_id": gloss_lookup_id,
            "token_id": token_id,
        },
    )


class TokenNotFound(Exception):
    pass


def correct_reading(conn, document_id: int, token_id: int, reading_hiragana: str) -> None:
    """Apply a user-supplied pronunciation for a token — for whenever
    Sudachi's own reading is wrong (三股 as みまた instead of さんまた) or
    nothing else offered a fix (no heteronym/split candidates existed, or
    the token is OOV and never had any to begin with).

    Reuses the same furigana alignment as automatic tokenization and the
    same conflicts-row mechanism as resolve_conflict, so this is fully
    redo-able too: it's just another row a later correction (or a return
    to a previous one) can supersede, nothing is thrown away. Also
    re-attempts the gloss lookup under the corrected reading — a wrong
    reading is often exactly why a real JMDict entry went unmatched.
    """
    # Same lock as resolve_conflict, same reason: serializes concurrent
    # calls for this one token rather than letting them race past the "one
    # selected row per token" unique index.
    token = conn.execute(
        text(
            """
            SELECT surface, normalized_form, dictionary_form, reading_katakana, furigana_spans, furigana_override
            FROM tokens
            WHERE id = :token_id AND document_id = :document_id
            FOR UPDATE
            """
        ),
        {"token_id": token_id, "document_id": document_id},
    ).one_or_none()

    if token is None:
        raise TokenNotFound()

    reading_katakana = to_katakana(reading_hiragana)
    spans = furigana_spans_for_reading(token.surface, reading_katakana)
    gloss_lookup_id = get_or_create_gloss_lookup(
        conn, token.normalized_form, reading_hiragana, alt_lookup_form=token.dictionary_form
    )

    has_prior_conflicts = conn.execute(
        text("SELECT EXISTS (SELECT 1 FROM conflicts WHERE token_id = :token_id)"),
        {"token_id": token_id},
    ).scalar_one()

    conn.execute(
        text("UPDATE conflicts SET selected = FALSE, selected_at = NULL WHERE token_id = :token_id"),
        {"token_id": token_id},
    )

    if not has_prior_conflicts:
        # First-ever correction for this token: preserve Sudachi's original
        # reading as an unselected row so "redo back to the original" stays
        # possible, the same as it always is for auto-flagged tokens.
        conn.execute(
            text(
                """
                INSERT INTO conflicts (token_id, kind, value, selected)
                VALUES (:token_id, 'custom', CAST(:value AS JSONB), FALSE)
                """
            ),
            {
                "token_id": token_id,
                "value": json.dumps(
                    {
                        "reading": to_hiragana(token.reading_katakana),
                        "furigana_spans": token.furigana_override or token.furigana_spans,
                        "citation_reading": mixed_reading(token.normalized_form),
                    }
                ),
            },
        )

    conn.execute(
        text(
            """
            INSERT INTO conflicts (token_id, kind, value, selected, selected_at)
            VALUES (:token_id, 'custom', CAST(:value AS JSONB), TRUE, now())
            """
        ),
        {
            "token_id": token_id,
            "value": json.dumps(
                {
                    "reading": reading_hiragana,
                    "furigana_spans": spans,
                    # The user's own input, used as-is — for a non-inflected
                    # word (the common case for a manual correction) this
                    # already is the citation reading; for an inflected one
                    # it's the best approximation available without deeper
                    # analysis of what they typed.
                    "citation_reading": reading_hiragana,
                }
            ),
        },
    )
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
            "furigana_spans": json.dumps(spans),
            "gloss_lookup_id": gloss_lookup_id,
            "token_id": token_id,
        },
    )
