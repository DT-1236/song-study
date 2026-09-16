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
from app.glosses import GlossPlan, get_or_create_gloss_lookup, gloss_piece, own_gloss_key, plan_glosses, store_glosses
from app.phrase_merge import MAX_PHRASE_TOKENS, light_verb_chain_end, light_verb_note
from app.tokenization import (
    TokenRecord,
    build_furigana_spans,
    citation_reading,
    conflict_option_value,
    conjugation_type_of,
    furigana_spans_for_reading,
    mixed_reading,
    project_citation_reading,
    slice_spans_by_token,
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


def create_phrase_conflicts(conn, document_id: int, records: list[TokenRecord]) -> None:
    """Insert one unselected review row per multi-token JMDict match
    app.phrase_merge found starting at a token — never pre-selected (see
    that module's docstring for why phrase matches are suggest-only, never
    auto-applied): a token can already have its own heteronym/no_kana_anchor
    conflict row selected as its default, and this just adds an independent
    option alongside it (the one-selected-per-token index only forbids two
    *selected* rows on the same token, not two rows of different kinds)."""
    rows = [
        # record.phrase_suggestion in full, not a hand-picked subset of its
        # keys — chain_start_offset (see app/phrase_merge.py) used to be
        # silently dropped here, which meant _apply_phrase_selection could
        # never tell a chain suggestion apart from an ordinary one once it
        # came back out of the conflicts table, and glossed it through the
        # wrong pipeline entirely (get_or_create_gloss_lookup's blind
        # SplitMode.A decomposition instead of _chain_extension_gloss_lookup).
        {"position": record.position, "value": record.phrase_suggestion}
        for record in records
        if record.phrase_suggestion is not None
    ]
    if not rows:
        return

    conn.execute(
        text(
            """
            INSERT INTO conflicts (token_id, kind, value, selected)
            SELECT t.id, 'phrase', c.value, FALSE
            FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS c(position int, value jsonb)
            JOIN tokens t ON t.document_id = :document_id AND t.position = c.position
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


def _recompute_phrase_furigana(conn, document_id: int, position: int, token_count: int, reading_hiragana: str) -> None:
    """After accepting a phrase (see _apply_phrase_selection), recompute
    furigana for the merged span from the phrase's own reading and split it
    back across the member tokens (tokenization.build_furigana_spans /
    slice_spans_by_token) — each token's existing furigana_spans was
    computed from Sudachi's own per-token reading before the merge existed,
    and that reading can be outright wrong for the idiom (期 alone reads き;
    この期に及んで needs ご).

    Left untouched (no override written, existing furigana kept) when the
    phrase's reading doesn't align with the merged surface at all — a
    dictionary-form completion (受け vs completed 受ける, see
    app/phrase_merge.py) has real morae the on-page text doesn't spell, so
    there's no way to divide it across characters. When only part of a
    kanji run is genuinely ambiguous (more than one valid per-character
    split, the same situation a single ordinary token's no_kana_anchor
    conflict already handles), the first valid split applies immediately as
    a default and every other one is offered as a 'phrase_furigana'
    conflict on the phrase's own first token — never marked `selected`,
    since these are alternate *readings of the same already-accepted
    phrase*, not a pick between different words, and marking one selected
    could collide with the phrase's own conflict row already selected on
    that same head token (conflicts_one_selected_per_token)."""
    members = conn.execute(
        text(
            """
            SELECT id, surface FROM tokens
            WHERE document_id = :document_id AND position >= :position AND position < :position + :token_count
            ORDER BY position
            """
        ),
        {"document_id": document_id, "position": position, "token_count": token_count},
    ).all()
    merged_surface = "".join(m.surface for m in members)
    token_lengths = [len(m.surface) for m in members]

    spans, needs_review, alternatives = build_furigana_spans(merged_surface, to_katakana(reading_hiragana))
    if needs_review and not alternatives:
        return

    default_sliced = slice_spans_by_token(spans, token_lengths)
    updates = [
        {"id": member.id, "furigana_override": sliced}
        for member, sliced in zip(members, default_sliced)
        if sliced is not None
    ]
    if updates:
        conn.execute(
            text(
                """
                UPDATE tokens t
                SET furigana_override = v.furigana_override
                FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS v(id int, furigana_override jsonb)
                WHERE t.id = v.id
                """
            ),
            {"rows": json.dumps(updates)},
        )

    if not alternatives:
        return

    head_token_id = members[0].id
    rows = []
    for alt_spans in alternatives:
        alt_sliced = slice_spans_by_token(alt_spans, token_lengths)
        alt_updates = [{"offset": i, "furigana_spans": sliced} for i, sliced in enumerate(alt_sliced) if sliced is not None]
        if alt_updates:
            rows.append({"token_id": head_token_id, "value": {"updates": alt_updates}})
    if rows:
        conn.execute(
            text(
                """
                INSERT INTO conflicts (token_id, kind, value, selected)
                SELECT token_id, 'phrase_furigana', CAST(value AS JSONB), FALSE
                FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS r(token_id int, value jsonb)
                """
            ),
            {"rows": json.dumps(rows)},
        )


def resolve_phrase_furigana(conn, document_id: int, conflict_id: int) -> list[int]:
    """Apply one of a phrase's alternative furigana splits (see
    _recompute_phrase_furigana). Returns the affected token ids, or raises
    ConflictNotFound if conflict_id isn't a phrase_furigana conflict in this
    document."""
    row = conn.execute(
        text(
            """
            SELECT c.value, t.position
            FROM conflicts c
            JOIN tokens t ON t.id = c.token_id
            WHERE c.id = :conflict_id AND c.kind = 'phrase_furigana' AND t.document_id = :document_id
            """
        ),
        {"conflict_id": conflict_id, "document_id": document_id},
    ).one_or_none()
    if row is None:
        raise ConflictNotFound()

    rows = conn.execute(
        text(
            """
            UPDATE tokens t
            SET furigana_override = v.furigana_override
            FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS v(position int, furigana_override jsonb)
            WHERE t.document_id = :document_id AND t.position = v.position
            RETURNING t.id
            """
        ),
        {
            "document_id": document_id,
            "rows": json.dumps(
                [{"position": row.position + u["offset"], "furigana_override": u["furigana_spans"]} for u in row.value["updates"]]
            ),
        },
    ).all()
    return [r.id for r in rows]


def _chain_extension_gloss_lookup(conn, document_id: int, head_token_id: int, position: int, value: dict) -> int:
    """The gloss_lookups id for accepting a phrase_suggestion that carries
    chain_start_offset (see app/phrase_merge.py's module docstring on the
    two-tier te+light-verb chain design) — glues the base's own gloss to a
    fresh lookup for each light verb in the chain, as a composite built
    directly rather than through get_or_create_gloss_lookup's normal
    pipeline. That pipeline would resolve value["lookup_form"] (the whole
    citation string, e.g. 真に受けてみる) as one unit, and since that whole
    string is never itself a JMDict headword, it would fall back to
    re-decomposing it from scratch via Sudachi's own SplitMode.A — which
    doesn't know 真に受ける is a lexicalized idiom and would silently split
    it back into literal 真/に/受ける, discarding its real, non-compositional
    meaning ("to take at face value") for a piece-by-piece gloss that
    doesn't mean the same thing.

    The base's own gloss comes from one of three places, distinguished not
    by chain_start_offset's numeric value but by which keys `value` carries
    (each producer sets exactly one combination — see phrase_merge.py):
      - `base_lookup_form`/`base_reading` present: an exact-match idiom or
        noun+する verbalization directly followed by a bare trailing
        connector with no light verb at all (見つけて回ってみたい's own
        chain aside — real case: 遠回りし+て, "took a detour and...", the
        connector trailing off with nothing further) — see
        phrase_merge._with_trailing_connector. The base was never actually
        merged/accepted on its own (this whole span is one single accept),
        so it needs a fresh lookup from its own already-verified
        lookup_form/reading, not head_token_id's current gloss.
      - chain_start_offset == 1 and neither of those keys present: the base
        is a bare verb/adjective with no other suggestion (offered directly
        — see phrase_merge._bare_light_verb_chain_suggestion) — a fresh
        single-token lookup, same convention as any ordinary token.
      - Otherwise (chain_start_offset > 1, no base_lookup_form): the base is
        a group that was already merged and accepted (an idiom or noun+す
        る verbalization) — this suggestion only exists because
        app.conflicts itself just offered it as a follow-up after that
        earlier accept (see the end of _apply_phrase_selection), so
        head_token_id's *current* gloss_lookup_id, from before this accept
        overwrites it, is exactly that already-resolved gloss.
    """
    chain_start_offset = value["chain_start_offset"]
    token_count = value["token_count"]
    # Neither a real Sudachi tag (an idiom/noun+する span is several tokens,
    # not one lexeme with its own part_of_speech) — the "*" fields just mean
    # heteronym_readings never matches, same net effect as skipping it.
    _compound_pos = ("動詞", "*", "*", "*", "*", "*")

    if "base_lookup_form" in value:
        base_gloss_id = get_or_create_gloss_lookup(conn, value["base_lookup_form"], value["base_reading"])
        base_pos = _compound_pos
    elif chain_start_offset == 1:
        base = conn.execute(
            text("SELECT normalized_form, dictionary_form, part_of_speech FROM tokens WHERE id = :token_id"),
            {"token_id": head_token_id},
        ).one()
        base_gloss_id = get_or_create_gloss_lookup(
            conn, base.normalized_form, mixed_reading(base.normalized_form), alt_lookup_form=base.dictionary_form
        )
        base_pos = base.part_of_speech
    else:
        base_gloss_id = conn.execute(
            text("SELECT gloss_lookup_id FROM tokens WHERE id = :token_id"), {"token_id": head_token_id}
        ).scalar_one()
        base_pos = _compound_pos

    base_row = conn.execute(
        text("SELECT lookup_form, reading, entries, source FROM gloss_lookups WHERE id = :id"),
        {"id": base_gloss_id},
    ).one()
    if base_row.source == "composite":
        pieces = list(base_row.entries["pieces"])
    else:
        pieces = [gloss_piece(base_row.lookup_form, base_row.reading, base_row.entries, base_row.source, base_pos)]

    members = conn.execute(
        text(
            """
            SELECT surface, dictionary_form, normalized_form, part_of_speech FROM tokens
            WHERE document_id = :document_id AND position >= :start AND position < :end
            ORDER BY position
            """
        ),
        {"document_id": document_id, "start": position + chain_start_offset, "end": position + token_count},
    ).all()
    # The chain alternates connector (て/で), light verb, connector, light
    # verb, ... — only the light verbs (odd indices here) get their own
    # gloss piece; the connectors are plain grammar, not vocabulary.
    for light_verb in members[1::2]:
        light_gloss_id = get_or_create_gloss_lookup(
            conn,
            light_verb.normalized_form,
            mixed_reading(light_verb.normalized_form),
            alt_lookup_form=light_verb.dictionary_form,
        )
        light_row = conn.execute(
            text("SELECT entries, source FROM gloss_lookups WHERE id = :id"), {"id": light_gloss_id}
        ).one()
        pieces.append(
            gloss_piece(
                light_verb.surface,
                mixed_reading(light_verb.normalized_form),
                light_row.entries,
                light_row.source,
                light_verb.part_of_speech,
                # This piece is always the light verb of a te-form chain
                # (light_verb_chain_end only ever selects a 非自立可能
                # occurrence) — its actual role is auxiliary regardless of
                # its own literal 動詞/形容詞 tag, so senses tagged
                # 'auxiliary verb' (JMDict's 助動詞 category) should rank
                # first when it has one (見る's てみる sense) rather than its
                # ordinary literal senses.
                senses_pos_major="助動詞",
                note=light_verb_note(light_verb.normalized_form),
            )
        )

    key = (value["lookup_form"], value["reading"])
    ids = store_glosses(conn, GlossPlan(cached_ids={}, new_rows={key: ({"pieces": pieces}, "composite")}))
    return ids[key]


def _project_onto_last_member(conn, document_id: int, last_position: int, citation_reading_hiragana: str) -> str:
    """`citation_reading_hiragana` trimmed down to what the on-page text
    through `last_position` (the last token of some span) actually spells,
    using that token's own conjugation (tokenization.project_citation_reading)
    — a citation-form completion (受け -> 受ける for 真に受ける) only ever
    touches a match's last token (see app/phrase_merge.py's exact-match
    search), so trimming against that one token's own dictionary_form vs.
    reading_katakana is enough regardless of how many tokens precede it.
    A no-op (returns citation_reading_hiragana unchanged) when that token
    needed no completion at all."""
    last = conn.execute(
        text(
            "SELECT reading_katakana, dictionary_form, normalized_form FROM tokens "
            "WHERE document_id = :document_id AND position = :position"
        ),
        {"document_id": document_id, "position": last_position},
    ).one()
    dict_form_citation = citation_reading(last.dictionary_form)
    conjugation_type = conjugation_type_of(last.normalized_form)
    projected = project_citation_reading(
        to_katakana(citation_reading_hiragana), last.reading_katakana, dict_form_citation, conjugation_type
    )
    return to_hiragana(projected)


def _offer_chain_extension(
    conn, document_id: int, head_token_id: int, position: int, token_count: int, base_surface: str
) -> None:
    """After accepting any phrase (an idiom, a noun+する verbalization, or a
    bare-verb light-verb chain itself), check whether the tokens
    immediately following the newly merged span form ANOTHER te+light-verb
    chain (light_verb_chain_end — see app/phrase_merge.py), and if so,
    offer combining them too, as a new, unselected 'phrase' conflict on the
    same head token — never applied automatically, same trust model as
    every other phrase suggestion.

    This is what lets 真に受け reveal 真に受けてみて only once accepted,
    rather than requiring both to be offered (and only one ever chosen
    between) at once — see app/phrase_merge.py's module docstring on why
    that split exists. It composes for free: accepting the revealed
    extension calls this same function again, against whatever follows
    *it* (真に受けてみてしまった, however unlikely in practice).

    lookup_form is deliberately the same as surface here (not, say,
    stitching the base's own possibly citation-completed lookup_form
    together with the chain) — chain_start_offset means the gloss is never
    actually looked up as one JMDict string at all (see
    _chain_extension_gloss_lookup), so lookup_form only needs to be a
    stable cache key and a natural-looking display string, which the
    literal on-page text already is.
    """
    following = conn.execute(
        text(
            """
            SELECT surface, dictionary_form, part_of_speech FROM tokens
            WHERE document_id = :document_id AND position >= :start
            ORDER BY position
            LIMIT :limit
            """
        ),
        {"document_id": document_id, "start": position + token_count, "limit": MAX_PHRASE_TOKENS},
    ).all()
    chain_end = light_verb_chain_end(following, 0, len(following))
    if chain_end is None:
        return

    chain_surface = "".join(r.surface for r in following[:chain_end])
    # The base span's own gloss reading can be dictionary-form-completed
    # beyond what's literally on the page (e.g. まにうける for surface
    # 真に受け, with a る that belongs to 受ける's citation form, not to any
    # on-page character) — concatenating that directly onto a continuing
    # chain would produce a wrong reading (まにうけるてみ instead of
    # まにうけてみ). _project_onto_last_member trims it back down.
    base_gloss_reading = conn.execute(
        text("SELECT gl.reading FROM tokens t JOIN gloss_lookups gl ON gl.id = t.gloss_lookup_id WHERE t.id = :head_id"),
        {"head_id": head_token_id},
    ).scalar_one()
    base_reading = _project_onto_last_member(conn, document_id, position + token_count - 1, base_gloss_reading)
    value = {
        "surface": base_surface + chain_surface,
        "lookup_form": base_surface + chain_surface,
        "reading": base_reading + mixed_reading(chain_surface),
        "token_count": token_count + chain_end,
        "chain_start_offset": token_count,
    }
    # Idempotent: a token can only ever have one live "reveal" suggestion at
    # a time, so any earlier one left over from a previous accept/unmerge
    # cycle on this same head is stale (real bug found live — repeated
    # accept/unmerge cycles piled up duplicate, identical reveal rows on the
    # same token instead of replacing the old one).
    conn.execute(
        text("DELETE FROM conflicts WHERE token_id = :token_id AND kind = 'phrase' AND NOT selected"),
        {"token_id": head_token_id},
    )
    conn.execute(
        text("INSERT INTO conflicts (token_id, kind, value, selected) VALUES (:token_id, 'phrase', CAST(:value AS JSONB), FALSE)"),
        {"token_id": head_token_id, "value": json.dumps(value)},
    )


def _apply_phrase_selection(conn, document_id: int, token_id: int, value: dict) -> list[int]:
    """Apply an accepted phrase suggestion (resolve_conflict's kind ==
    'phrase' branch): give every token in the run the phrase's own
    gloss_lookup_id, mark them as one group via phrase_start_position, and
    recompute their furigana from the phrase's own reading where that's
    possible (see _recompute_phrase_furigana). Also offers a further
    te+light-verb chain extension, if one immediately follows the newly
    merged span, as a new, separate, unselected suggestion (see
    _offer_chain_extension) — never applied automatically, same as every
    other phrase suggestion. Returns the affected token ids. Reversible via
    unmerge_phrase, given any member token id."""
    position = conn.execute(
        text("SELECT position FROM tokens WHERE id = :token_id"),
        {"token_id": token_id},
    ).scalar_one()

    # The fusion being accepted always takes precedence over any other one
    # partially overlapping it: a token this span is about to claim can
    # already be a member of a DIFFERENT, independently-generated merge
    # (see app/phrase_merge.py's module docstring on why overlapping
    # suggestions at different starting positions are allowed to coexist,
    # deliberately, as suggestions) — real corruption found live: accepting
    # a smaller suggestion (受けてみ, its own tier-3 bare-verb-chain
    # suggestion starting mid-idiom) before the idiom containing its first
    # token (真に受け) left 真/に stranded, still tagged with the idiom's
    # phrase_start_position, once the idiom was accepted afterward and
    # silently reassigned only 受け (the overlapping tail) to itself.
    # Reverting any such other group first, before this one applies,
    # guarantees the just-accepted fusion's own span ends up consistent
    # regardless of what order suggestions were accepted in.
    stale_group_starts = conn.execute(
        text(
            """
            SELECT DISTINCT phrase_start_position FROM tokens
            WHERE document_id = :document_id
              AND position >= :position AND position < :position + :token_count
              AND phrase_start_position IS NOT NULL AND phrase_start_position != :position
            """
        ),
        {"document_id": document_id, "position": position, "token_count": value["token_count"]},
    ).scalars().all()
    for group_start in stale_group_starts:
        other_member_id = conn.execute(
            text("SELECT id FROM tokens WHERE document_id = :document_id AND position = :position"),
            {"document_id": document_id, "position": group_start},
        ).scalar_one()
        unmerge_phrase(conn, document_id, other_member_id)

    if value.get("chain_start_offset") is not None:
        gloss_lookup_id = _chain_extension_gloss_lookup(conn, document_id, token_id, position, value)
    else:
        # lookup_form (not value["surface"]) is what's actually verified as
        # a JMDict headword — for a plain match they're identical, but for
        # a dictionary-form completion (真に受け -> 真に受ける) the raw
        # on-page surface alone has no entry at all (see app/phrase_merge.py).
        gloss_lookup_id = get_or_create_gloss_lookup(conn, value["lookup_form"], value["reading"])
    rows = conn.execute(
        text(
            """
            UPDATE tokens
            SET gloss_lookup_id = :gloss_lookup_id, phrase_start_position = :position
            WHERE document_id = :document_id
              AND position >= :position AND position < :position + :token_count
            RETURNING id
            """
        ),
        {
            "document_id": document_id,
            "position": position,
            "token_count": value["token_count"],
            "gloss_lookup_id": gloss_lookup_id,
        },
    ).all()

    # Every other member (not the head, whose own conflicts are handled by
    # resolve_conflict/​_offer_chain_extension) just became part of this
    # fusion, so it can no longer independently start its own separate one
    # — any unselected 'phrase' suggestion still sitting on it (like 受け's
    # own tier-3 受けてみ suggestion, independently generated at
    # tokenization time — see app/phrase_merge.py) is now stale and must be
    # cancelled, or accepting it later would silently re-split this fusion.
    conn.execute(
        text(
            """
            DELETE FROM conflicts
            WHERE kind = 'phrase' AND NOT selected
              AND token_id IN (
                  SELECT id FROM tokens
                  WHERE document_id = :document_id AND position > :position AND position < :position + :token_count
              )
            """
        ),
        {"document_id": document_id, "position": position, "token_count": value["token_count"]},
    )

    on_page_reading = _project_onto_last_member(conn, document_id, position + value["token_count"] - 1, value["reading"])
    _recompute_phrase_furigana(conn, document_id, position, value["token_count"], on_page_reading)
    _offer_chain_extension(conn, document_id, token_id, position, value["token_count"], value["surface"])
    return [row.id for row in rows]


def unmerge_phrase(conn, document_id: int, token_id: int) -> list[int]:
    """Undo an accepted phrase suggestion: revert every token in `token_id`'s
    group (found via its shared phrase_start_position — `token_id` may be
    any member, not just the group's first token) back to its own
    individual gloss, the same one gloss_key/attach_glosses would compute
    for it outside of any phrase, and clear phrase_start_position on all of
    them. Returns the affected token ids, or [] if `token_id` isn't
    currently part of a merged phrase (nothing to undo). Raises
    TokenNotFound if `token_id` doesn't belong to `document_id` at all.

    A token's own prior reading pick (heteronym/custom) isn't recoverable
    here if resolving the phrase conflict deselected it — see
    resolve_conflict's comment on conflicts_one_selected_per_token; such a
    token reverts to its citation-form default rather than that pick.
    """
    locked = conn.execute(
        text(
            """
            SELECT phrase_start_position FROM tokens
            WHERE id = :token_id AND document_id = :document_id
            FOR UPDATE
            """
        ),
        {"token_id": token_id, "document_id": document_id},
    ).one_or_none()
    if locked is None:
        raise TokenNotFound()
    group_start = locked.phrase_start_position
    if group_start is None:
        return []

    # The phrase's own conflict row (on the group's first token) is still
    # selected at this point — excluded here so it can't leak its reading
    # into that token's own recompute below, and deselected explicitly
    # after, so the suggestion is offerable again (accept/unmerge toggle).
    members = conn.execute(
        text(
            """
            SELECT t.id, t.normalized_form, t.dictionary_form, t.part_of_speech,
                   COALESCE(c.value ->> 'citation_reading', c.value ->> 'reading') AS selected_reading
            FROM tokens t
            LEFT JOIN conflicts c ON c.token_id = t.id AND c.selected AND c.kind != 'phrase'
            WHERE t.document_id = :document_id AND t.phrase_start_position = :group_start
            ORDER BY t.position
            """
        ),
        {"document_id": document_id, "group_start": group_start},
    ).all()
    conn.execute(
        text(
            """
            UPDATE conflicts SET selected = FALSE, selected_at = NULL
            WHERE kind = 'phrase' AND selected
              AND token_id IN (SELECT id FROM tokens WHERE document_id = :document_id AND phrase_start_position = :group_start)
            """
        ),
        {"document_id": document_id, "group_start": group_start},
    )

    keys: dict[int, tuple] = {}
    requests = []
    for member in members:
        key = own_gloss_key(member.normalized_form, member.part_of_speech, member.selected_reading)
        if key is None:
            continue
        keys[member.id] = key
        requests.append((key, member.dictionary_form))

    if keys:
        gloss_ids = store_glosses(conn, plan_glosses(conn, requests))
        conn.execute(
            text(
                """
                UPDATE tokens t
                SET gloss_lookup_id = v.gloss_lookup_id
                FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS v(id int, gloss_lookup_id int)
                WHERE t.id = v.id
                """
            ),
            {"rows": json.dumps([{"id": token_id, "gloss_lookup_id": gloss_ids[key]} for token_id, key in keys.items()])},
        )
    # Clears furigana_override too: _apply_phrase_selection may have
    # written the phrase's own combined reading across these tokens (see
    # _recompute_phrase_furigana), which no longer applies once they're
    # back on their own individual glosses. Its phrase_furigana alternative
    # rows (kind='phrase_furigana', on the group's own first token) are
    # deleted rather than left dangling, so re-accepting the phrase later
    # regenerates them fresh instead of piling up duplicates.
    conn.execute(
        text(
            """
            UPDATE tokens SET phrase_start_position = NULL, furigana_override = NULL
            WHERE document_id = :document_id AND phrase_start_position = :group_start
            """
        ),
        {"document_id": document_id, "group_start": group_start},
    )
    conn.execute(
        text(
            """
            DELETE FROM conflicts
            WHERE kind = 'phrase_furigana'
              AND token_id IN (SELECT id FROM tokens WHERE document_id = :document_id AND position = :group_start)
            """
        ),
        {"document_id": document_id, "group_start": group_start},
    )
    return [member.id for member in members]


class ConflictNotFound(Exception):
    pass


def resolve_conflict(conn, document_id: int, token_id: int, conflict_id: int) -> list[int]:
    """Select `conflict_id` among `token_id`'s conflict rows and apply it.
    Returns every token id the selection actually changed the gloss of:
    just [token_id] for an ordinary reading conflict, or the whole run for
    an accepted phrase suggestion (see app/phrase_merge.py)."""
    # Locks the token row for the rest of this transaction, so a second
    # resolve/correct call for the SAME token (a double-click, or two tabs)
    # blocks until this one commits instead of racing it — both would
    # otherwise read "nothing selected yet" and each insert their own
    # selected=true row, tripping the "one selected row per token" unique
    # index. Concurrent calls for DIFFERENT tokens are unaffected.
    owner = conn.execute(
        text(
            """
            SELECT c.kind, c.value
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
    kind, value = owner.kind, owner.value

    # conflicts_one_selected_per_token allows at most one selected row per
    # token_id regardless of kind, so accepting a phrase suggestion here
    # necessarily deselects any reading conflict (heteronym/no_kana_anchor/
    # custom) already selected on this exact token — known limitation: if
    # the phrase is later unmerged (conflicts.unmerge_phrase), this token
    # reverts to its citation-form default reading rather than whatever was
    # previously picked for it, since that pick is no longer marked
    # selected anywhere to recover it from.
    conn.execute(
        text("UPDATE conflicts SET selected = FALSE, selected_at = NULL WHERE token_id = :token_id"),
        {"token_id": token_id},
    )
    conn.execute(
        text("UPDATE conflicts SET selected = TRUE, selected_at = now() WHERE id = :conflict_id"),
        {"conflict_id": conflict_id},
    )

    if kind == "phrase":
        return _apply_phrase_selection(conn, document_id, token_id, value)

    # Picking an ordinary reading for a token that's currently merged into
    # a phrase (see app/phrase_merge.py) would otherwise silently desync
    # just this one token from its siblings, still sharing the phrase's
    # gloss, without ever clearing phrase_start_position — a real bug
    # found live: a heteronym pick on 真 after merging 真に受ける left 真
    # alone reglossed as a plain word while に/受け still showed the
    # idiom. Unmerging the whole group first keeps every member consistent
    # (all reverted to their own gloss) before the new reading applies.
    unmerged = unmerge_phrase(conn, document_id, token_id)

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
    return list({token_id, *unmerged})


def accept_phrase_suggestions(conn, document_id: int, conflict_ids: list[int]) -> list[int]:
    """Accept several phrase suggestions in one call — e.g. every matching
    instance of the same word's suggestion (see DocumentViewPage.tsx's
    matchingPhraseSuggestions), applied together instead of one at a time.
    Each conflict_id's own token_id is looked up here (the caller only
    needs the conflict ids, already at hand on each candidate token), and
    every conflict is resolved the same way a single accept-phrase call
    would (see resolve_conflict) — just within one transaction instead of
    one request per instance. Returns every token id any of them affected.
    Raises ConflictNotFound if any conflict_id doesn't belong to this
    document's tokens."""
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.token_id
            FROM conflicts c
            JOIN tokens t ON t.id = c.token_id
            WHERE c.id = ANY(:conflict_ids) AND t.document_id = :document_id
            """
        ),
        {"conflict_ids": conflict_ids, "document_id": document_id},
    ).all()
    if len(rows) != len(set(conflict_ids)):
        raise ConflictNotFound()

    affected: list[int] = []
    for row in rows:
        affected.extend(resolve_conflict(conn, document_id, row.token_id, row.id))
    return affected


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
