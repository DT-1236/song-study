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

from app.db import json_param
from app.glosses import (
    KATAKANA_GLOSS_COLUMNS,
    KATAKANA_GLOSS_SQL,
    GlossKey,
    GroupGlossRequest,
    GroupPart,
    alternate_reading_options,
    attach_glosses,
    get_or_create_gloss_lookup,
    gloss_entries,
    is_word_piece,
    own_gloss_key,
    picked_katakana_gloss,
    piece_current_idseq,
    plan_glosses,
    predicate_group_request,
    store_glosses,
    word_options,
)
from app.tokenization import (
    TokenRecord,
    build_furigana_spans,
    citation_reading,
    conflict_option_value,
    conjugation_type_of,
    furigana_spans_for_reading,
    headword_reading,
    project_citation_reading,
    slice_spans_by_token,
    to_hiragana,
    to_katakana,
)

# Conflict kinds that aren't reading options for their token: a phrase
# suggestion, a merged phrase's alternative furigana, and a predicate group
# that can be merged again after being split.
NON_READING_KINDS = ("phrase", "phrase_furigana", "predicate")

# The selected phrase suggestion on the head of the group `t` is merged
# into: NULL unless that group is an accepted phrase rather than a predicate
# group.
ACCEPTED_PHRASE_SQL = """
    (
        SELECT pc.value FROM conflicts pc JOIN tokens ph ON ph.id = pc.token_id
        WHERE ph.document_id = t.document_id AND ph.position = t.phrase_start_position
          AND pc.kind = 'phrase' AND pc.selected
    )
"""
IS_ACCEPTED_PHRASE_SQL = f"{ACCEPTED_PHRASE_SQL} IS NOT NULL"


def create_conflicts(conn, document_id: int, records: list[TokenRecord]) -> None:
    """Insert a selected default plus unselected alternatives for every
    flagged record, attached to the document's already-inserted tokens."""
    rows = []
    for record in records:
        if not record.conflict_options:
            continue
        # `reading` below is the inflected surface's own reading (what
        # furigana needs); `citation_reading` is deliberately different —
        # the citation form's reading, from headword_reading, which is
        # what a later gloss lookup is actually keyed by. These
        # differ for an inflected token (揃える's citation reading そろえる
        # vs 揃え's own reading そろえ).
        default_value = conflict_option_value(
            to_hiragana(record.reading_katakana),
            record.furigana_spans,
            headword_reading(record.normalized_form, record.dictionary_form),
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


def create_phrase_conflicts(
    conn, document_id: int, records: list[TokenRecord], groups: list[range]
) -> None:
    """Insert an unselected 'phrase' row for each record's phrase suggestion,
    and a 'predicate' row on the first token of each of `groups`, which
    merges that group again after it's split."""
    rows = [
        {
            "position": record.position,
            "kind": "phrase",
            "value": record.phrase_suggestion,
        }
        for record in records
        if record.phrase_suggestion is not None
    ]
    rows.extend(
        {
            "position": records[group.start].position,
            "kind": "predicate",
            "value": {
                "surface": "".join(records[i].surface for i in group),
                "token_count": len(group),
            },
        }
        for group in groups
    )
    if not rows:
        return

    conn.execute(
        text(
            """
            INSERT INTO conflicts (token_id, kind, value, selected)
            SELECT t.id, c.kind, c.value, FALSE
            FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS c(position int, kind text, value jsonb)
            JOIN tokens t ON t.document_id = :document_id AND t.position = c.position
            """
        ),
        {"document_id": document_id, "rows": json.dumps(rows)},
    )


def _apply_selected_reading(
    conn, token_id: int, furigana_spans: list[dict], gloss_lookup_id: int
) -> None:
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


def _recompute_phrase_furigana(
    conn, document_id: int, position: int, token_count: int, reading_hiragana: str
) -> None:
    """Set the furigana of the document's `token_count` tokens from
    `position` from their phrase's reading, `reading_hiragana`, since a
    phrase can read differently from its tokens (期 reads ご in この期に及んで).
    Any other valid split of the reading is offered as a 'phrase_furigana'
    row on the first token."""
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

    spans, needs_review, alternatives = build_furigana_spans(
        merged_surface, to_katakana(reading_hiragana)
    )
    # The reading doesn't line up with the text, so the tokens keep their own.
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
        alt_updates = [
            {"offset": i, "furigana_spans": sliced}
            for i, sliced in enumerate(alt_sliced)
            if sliced is not None
        ]
        if alt_updates:
            rows.append({"token_id": head_token_id, "value": {"updates": alt_updates}})
    if rows:
        # Unselected: selecting one would deselect the phrase itself, on the
        # same token.
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
    """Apply `conflict_id`, one of a phrase's alternative furigana splits.
    Returns the affected token ids. Raises ConflictNotFound if it isn't a
    phrase_furigana row in `document_id`."""
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
                [
                    {
                        "position": row.position + u["offset"],
                        "furigana_override": u["furigana_spans"],
                    }
                    for u in row.value["updates"]
                ]
            ),
        },
    ).all()
    return [r.id for r in rows]


def _project_onto_member(member, citation_reading_hiragana: str) -> str:
    """`citation_reading_hiragana`, a headword's reading, as spelled on the
    page through `member`, a token row that can inflect the headword's last
    word (まにうける -> まにうけ for 真に受け)."""
    dict_form_citation = citation_reading(member.dictionary_form)
    conjugation_type = conjugation_type_of(member.normalized_form)
    projected = project_citation_reading(
        to_katakana(citation_reading_hiragana),
        member.reading_katakana,
        dict_form_citation,
        conjugation_type,
    )
    return to_hiragana(projected)


def _members_by_start(conn, document_id: int, spans: dict[int, int]) -> dict[int, list]:
    """The document's tokens in each of `spans`, a token count by start
    position, keyed by that start: in order, each with its selected reading
    option's readings, if it has one."""
    rows = conn.execute(
        text(
            """
            SELECT s.start, t.id, t.surface, t.reading_katakana, t.dictionary_form, t.normalized_form, t.part_of_speech,
                   c.value ->> 'reading' AS selected_reading,
                   COALESCE(c.value ->> 'citation_reading', c.value ->> 'reading') AS selected_citation_reading
            FROM jsonb_to_recordset(CAST(:spans AS JSONB)) AS s(start int, token_count int)
            JOIN tokens t ON t.document_id = :document_id AND t.position >= s.start AND t.position < s.start + s.token_count
            LEFT JOIN conflicts c ON c.token_id = t.id AND c.selected AND c.kind <> ALL(:non_reading_kinds)
            ORDER BY t.position
            """
        ),
        {
            "document_id": document_id,
            "spans": json.dumps(
                [
                    {"start": start, "token_count": token_count}
                    for start, token_count in spans.items()
                ]
            ),
            "non_reading_kinds": list(NON_READING_KINDS),
        },
    ).all()
    members: dict[int, list] = {start: [] for start in spans}
    for row in rows:
        members[row.start].append(row)
    return members


def _group_members(conn, document_id: int, position: int, token_count: int) -> list:
    """The document's `token_count` tokens from `position`, in order, each
    with its selected reading option's readings, if it has one."""
    return _members_by_start(conn, document_id, {position: token_count})[position]


def _page_reading(member) -> str:
    """A token row's reading on the page, in hiragana: its selected option's,
    or else Sudachi's."""
    return member.selected_reading or to_hiragana(member.reading_katakana)


def _merge_groups(
    conn, document_id: int, groups: list[tuple[int, int, int]]
) -> list[int]:
    """Mark each of `groups`, a (start position, token count, gloss lookup
    id), as one group of the document's tokens sharing that gloss. Returns
    their ids."""
    rows = conn.execute(
        text(
            """
            UPDATE tokens t
            SET gloss_lookup_id = g.gloss_lookup_id, phrase_start_position = g.start
            FROM jsonb_to_recordset(CAST(:groups AS JSONB))
                AS g(start int, token_count int, gloss_lookup_id int)
            WHERE t.document_id = :document_id AND t.position >= g.start AND t.position < g.start + g.token_count
            RETURNING t.id
            """
        ),
        {
            "document_id": document_id,
            "groups": json.dumps(
                [
                    {"start": start, "token_count": count, "gloss_lookup_id": gloss_id}
                    for start, count, gloss_id in groups
                ]
            ),
        },
    ).all()
    return [row.id for row in rows]


def _merge_tokens(
    conn, document_id: int, position: int, token_count: int, gloss_lookup_id: int
) -> list[int]:
    """Mark the document's `token_count` tokens from `position` as one group
    sharing `gloss_lookup_id`. Returns their ids."""
    return _merge_groups(conn, document_id, [(position, token_count, gloss_lookup_id)])


def _predicate_request(members: list) -> GroupGlossRequest:
    """The gloss request for a predicate group of `members`, token rows
    from _group_members, under each one's current reading."""
    head = members[0]
    return predicate_group_request(
        members,
        [_page_reading(member) for member in members],
        own_gloss_key(head, head.selected_citation_reading),
    )


def _gloss_ids(conn, requests: list[GlossKey | GroupGlossRequest]) -> list[int]:
    """The gloss_lookups id of each of `requests`, a plain key or a group's
    request, in order, caching any not cached yet."""
    groups = [r for r in requests if isinstance(r, GroupGlossRequest)]
    # A plain key here is a phrase's headword, which has no alternate
    # spelling to try.
    keys = [(r, None) for r in requests if not isinstance(r, GroupGlossRequest)]
    ids = store_glosses(conn, plan_glosses(conn, keys, groups))
    return [ids[r.key if isinstance(r, GroupGlossRequest) else r] for r in requests]


def merge_predicate_group(
    conn, document_id: int, position: int, token_count: int
) -> list[int]:
    """Merge the document's `token_count` tokens from `position` into a
    predicate group (see app.grammar), glossed together under each token's
    current reading. Returns their ids."""
    members = _group_members(conn, document_id, position, token_count)
    [gloss_lookup_id] = _gloss_ids(conn, [_predicate_request(members)])
    return _merge_tokens(conn, document_id, position, token_count, gloss_lookup_id)


def repair_gloss_links(conn, document_id: int) -> None:
    """Link a gloss to every token of the document that should have one but
    has none, as a migration clearing stale glosses leaves them: each group
    member to its group's gloss, every other token to its own."""
    # Each group with a member linked to no gloss.
    starts = (
        conn.execute(
            text(
                """
                SELECT phrase_start_position FROM tokens
                WHERE document_id = :document_id AND phrase_start_position IS NOT NULL
                GROUP BY phrase_start_position
                HAVING bool_or(gloss_lookup_id IS NULL)
                """
            ),
            {"document_id": document_id},
        )
        .scalars()
        .all()
    )
    _regloss_groups(conn, document_id, starts)
    attach_glosses(conn, document_id)


def _regloss_groups(conn, document_id: int, starts: list[int]) -> list[int]:
    """Gloss again each of the document's groups starting at one of
    `starts`, under its members' current readings: an accepted phrase under
    its headword, a predicate group as its word plus its grammar. Returns
    their token ids."""
    if not starts:
        return []
    groups = conn.execute(
        text(
            f"""
            SELECT t.phrase_start_position AS start, count(*) AS member_count,
                   {ACCEPTED_PHRASE_SQL} AS phrase
            FROM tokens t
            WHERE t.document_id = :document_id AND t.phrase_start_position = ANY(:starts)
            GROUP BY t.document_id, t.phrase_start_position
            ORDER BY t.phrase_start_position
            """
        ),
        {"document_id": document_id, "starts": starts},
    ).all()
    # A phrase spans the tokens its suggestion covers; a predicate group,
    # every token merged into it.
    spans = {
        group.start: group.phrase["token_count"] if group.phrase else group.member_count
        for group in groups
    }
    members = _members_by_start(conn, document_id, spans)
    requests = [
        _phrase_request(members[group.start], group.phrase)[0]
        if group.phrase
        else _predicate_request(members[group.start])
        for group in groups
    ]
    gloss_ids = _gloss_ids(conn, requests)
    return _merge_groups(
        conn,
        document_id,
        [
            (group.start, spans[group.start], gloss_id)
            for group, gloss_id in zip(groups, gloss_ids)
        ],
    )


def _unmerge_overlapping_groups(
    conn, document_id: int, position: int, token_count: int
) -> list[int]:
    """Split every group with a member among the document's `token_count`
    tokens from `position`. Returns the affected token ids."""
    # One member of each group is enough for unmerge_phrase to find it.
    member_ids = (
        conn.execute(
            text(
                """
            SELECT DISTINCT ON (phrase_start_position) id FROM tokens
            WHERE document_id = :document_id AND position >= :position AND position < :position + :token_count
              AND phrase_start_position IS NOT NULL
            ORDER BY phrase_start_position, position
            """
            ),
            {
                "document_id": document_id,
                "position": position,
                "token_count": token_count,
            },
        )
        .scalars()
        .all()
    )
    affected: list[int] = []
    for member_id in member_ids:
        affected.extend(unmerge_phrase(conn, document_id, member_id))
    return affected


def _phrase_request(
    members: list, value: dict
) -> tuple[GlossKey | GroupGlossRequest, str]:
    """The gloss request and full reading of the phrase suggestion `value`
    (see app.phrase_merge) over `members`, its token rows from
    _group_members: the phrase's headword, plus a piece per token of grammar
    attached after it if there is any."""
    phrase_token_count = value.get("phrase_token_count", value["token_count"])
    attached = members[phrase_token_count:]
    # The headword's reading can spell more than the page does: まにうける
    # for 真に受け.
    phrase_reading = _project_onto_member(
        members[phrase_token_count - 1], value["reading"]
    )
    reading = phrase_reading + "".join(_page_reading(member) for member in attached)
    base_key = (value["lookup_form"], value["reading"])
    if not attached:
        return base_key, reading
    request = GroupGlossRequest(
        base_key=base_key,
        base_alt=None,
        # No one token's part of speech is the phrase's, so its senses keep
        # JMDict's order.
        base_part_of_speech=("*",) * 6,
        attached=tuple(
            GroupPart.of(member, _page_reading(member)) for member in attached
        ),
        reading=reading,
    )
    return request, reading


def _apply_phrase_selection(
    conn, document_id: int, token_id: int, value: dict
) -> list[int]:
    """Merge an accepted phrase suggestion's tokens (see app.phrase_merge)
    into one group, glossed under the phrase's headword plus a piece per
    token of grammar attached after it, and recompute their furigana from
    the phrase's reading. Returns their ids."""
    position = conn.execute(
        text("SELECT position FROM tokens WHERE id = :token_id"),
        {"token_id": token_id},
    ).scalar_one()
    token_count = value["token_count"]
    request, reading = _phrase_request(
        _group_members(conn, document_id, position, token_count), value
    )
    [gloss_lookup_id] = _gloss_ids(conn, [request])
    ids = _merge_tokens(conn, document_id, position, token_count, gloss_lookup_id)

    # A member can no longer start a phrase of its own inside this one:
    # accepting that later would split this phrase apart.
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
        {"document_id": document_id, "position": position, "token_count": token_count},
    )
    _recompute_phrase_furigana(conn, document_id, position, token_count, reading)
    return ids


def unmerge_phrase(conn, document_id: int, token_id: int) -> list[int]:
    """Split the group `token_id` is merged into — an accepted phrase or a
    predicate group, found from any member — back into tokens with their
    own glosses and furigana. Returns the affected token ids, or [] if
    `token_id` isn't merged. Raises TokenNotFound if `token_id` doesn't
    belong to `document_id`.

    Accepting a phrase deselected its first token's own reading pick (see
    resolve_conflict), so that token reverts to its default reading."""
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

    # Deselected so the phrase can be accepted again.
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
    members = conn.execute(
        text(
            """
            SELECT t.id, t.surface, t.normalized_form, t.dictionary_form, t.part_of_speech,
                   COALESCE(c.value ->> 'citation_reading', c.value ->> 'reading') AS selected_reading,
                   c.value -> 'furigana_spans' AS selected_furigana_spans
            FROM tokens t
            LEFT JOIN conflicts c ON c.token_id = t.id AND c.selected AND c.kind <> ALL(:non_reading_kinds)
            WHERE t.document_id = :document_id AND t.phrase_start_position = :group_start
            ORDER BY t.position
            """
        ),
        {
            "document_id": document_id,
            "group_start": group_start,
            "non_reading_kinds": list(NON_READING_KINDS),
        },
    ).all()

    keys = {
        member.id: key
        for member in members
        if (key := own_gloss_key(member, member.selected_reading)) is not None
    }
    gloss_ids = store_glosses(
        conn,
        plan_glosses(
            conn, [(keys[m.id], m.dictionary_form) for m in members if m.id in keys]
        ),
    )
    # A phrase's furigana (see _recompute_phrase_furigana) gives way to each
    # token's own selected option's, or none.
    conn.execute(
        text(
            """
            UPDATE tokens t
            SET phrase_start_position = NULL,
                gloss_lookup_id = v.gloss_lookup_id,
                furigana_override = v.furigana_override
            FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS v(id int, gloss_lookup_id int, furigana_override jsonb)
            WHERE t.id = v.id
            """
        ),
        {
            "rows": json.dumps(
                [
                    {
                        "id": member.id,
                        "gloss_lookup_id": gloss_ids[keys[member.id]]
                        if member.id in keys
                        else None,
                        "furigana_override": member.selected_furigana_spans,
                    }
                    for member in members
                ]
            )
        },
    )
    # Accepting the phrase again regenerates these.
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


def _select_conflict(conn, token_id: int, conflict_id: int) -> None:
    """Make `conflict_id` the only selected conflict row of `token_id`."""
    # Deselected first: conflicts_one_selected_per_token allows one selected
    # row per token, whatever its kind.
    conn.execute(
        text(
            "UPDATE conflicts SET selected = FALSE, selected_at = NULL WHERE token_id = :token_id"
        ),
        {"token_id": token_id},
    )
    conn.execute(
        text(
            "UPDATE conflicts SET selected = TRUE, selected_at = now() WHERE id = :conflict_id"
        ),
        {"conflict_id": conflict_id},
    )


def resolve_conflict(
    conn, document_id: int, token_id: int, conflict_id: int
) -> list[int]:
    """Apply `conflict_id`, one of `token_id`'s conflict rows: select a
    reading, accept a phrase suggestion, or merge a split predicate group
    again. Returns every token id whose gloss changed."""
    # Locks the token row for the rest of this transaction, so a second
    # resolve/correct call for the SAME token (a double-click, or two tabs)
    # blocks until this one commits instead of racing it — both would
    # otherwise read "nothing selected yet" and each insert their own
    # selected=true row, tripping the "one selected row per token" unique
    # index. Concurrent calls for DIFFERENT tokens are unaffected.
    owner = conn.execute(
        text(
            f"""
            SELECT c.kind, c.value, t.position, t.phrase_start_position,
                   {IS_ACCEPTED_PHRASE_SQL} AS in_accepted_phrase
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

    if kind == "predicate":
        # Never selected: that would deselect the head's reading.
        affected = _unmerge_overlapping_groups(
            conn, document_id, owner.position, value["token_count"]
        )
        return list(
            {
                *affected,
                *merge_predicate_group(
                    conn, document_id, owner.position, value["token_count"]
                ),
            }
        )

    if kind == "phrase":
        affected = _unmerge_overlapping_groups(
            conn, document_id, owner.position, value["token_count"]
        )
        # Known limitation: this deselects a reading picked for this token,
        # which unmerging the phrase later can't recover.
        _select_conflict(conn, token_id, conflict_id)
        return list(
            {*affected, *_apply_phrase_selection(conn, document_id, token_id, value)}
        )

    # A reading picked inside an accepted phrase would leave this token's
    # gloss out of step with the rest of the phrase, so the phrase is split
    # first. A predicate group is glossed again with the new reading instead.
    unmerged = (
        unmerge_phrase(conn, document_id, token_id) if owner.in_accepted_phrase else []
    )
    _select_conflict(conn, token_id, conflict_id)

    token = conn.execute(
        text(
            "SELECT normalized_form, dictionary_form FROM tokens WHERE id = :token_id"
        ),
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
    affected = {token_id, *unmerged}
    if owner.phrase_start_position is not None and not owner.in_accepted_phrase:
        affected.update(
            _regloss_groups(conn, document_id, [owner.phrase_start_position])
        )
    return list(affected)


def accept_phrase_suggestions(
    conn, document_id: int, conflict_ids: list[int]
) -> list[int]:
    """Apply each of `conflict_ids` as resolve_conflict does, such as every
    instance of the same phrase suggestion. Returns every token id any of
    them changed. Raises ConflictNotFound if one isn't in `document_id`."""
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
    reading_hiragana: str | None = None,
    furigana_spans: list[dict] | None = None,
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
    # lock's previous holder committed. Only reading options count, since
    # the other kinds depend on the tokens around each one.
    tokens = conn.execute(
        text(
            f"""
            SELECT t.id, t.surface, t.normalized_form, t.dictionary_form, t.reading_katakana,
                   t.furigana_spans, t.furigana_override, t.phrase_start_position,
                   {IS_ACCEPTED_PHRASE_SQL} AS in_accepted_phrase,
                   jsonb_build_array(
                       t.surface, t.reading_katakana, t.part_of_speech,
                       COALESCE(
                           (SELECT jsonb_agg(c.value ORDER BY c.id) FROM conflicts c
                            WHERE c.token_id = t.id AND c.kind <> 'custom' AND c.kind <> ALL(:non_reading_kinds)),
                           CAST('[]' AS JSONB)
                       )
                   ) AS group_key,
                   EXISTS (
                       SELECT 1 FROM conflicts c WHERE c.token_id = t.id AND c.kind <> ALL(:non_reading_kinds)
                   ) AS has_options,
                   m.id AS match_id, m.value AS match_value
            FROM tokens t
            LEFT JOIN LATERAL (
                SELECT c.id, c.value
                FROM conflicts c
                WHERE c.token_id = t.id AND c.kind <> ALL(:non_reading_kinds) AND c.value ->> 'reading' = :reading
                ORDER BY c.kind = 'custom',
                         c.value -> 'furigana_spans' = CAST(:furigana_spans AS JSONB) DESC NULLS LAST,
                         c.id
                LIMIT 1
            ) m ON TRUE
            WHERE t.id = ANY(:token_ids)
            ORDER BY t.id
            """
        ),
        {
            "token_ids": token_ids,
            "reading": reading_hiragana,
            "furigana_spans": json_param(furigana_spans),
            "non_reading_kinds": list(NON_READING_KINDS),
        },
    ).all()
    if len({json.dumps(t.group_key, sort_keys=True) for t in tokens}) > 1:
        raise TokensNotGroupable()
    return tokens


def select_reading(
    conn,
    document_id: int,
    token_ids: list[int],
    reading_hiragana: str,
    furigana_spans: list[dict] | None = None,
) -> list[int]:
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
    unmatched. Returns every token id whose gloss changed, which includes
    the rest of any group one of them is in."""
    tokens = lock_token_group(
        conn, document_id, token_ids, reading_hiragana, furigana_spans
    )
    # As in resolve_conflict: an accepted phrase is split first, and a
    # predicate group is glossed again afterwards.
    affected = set(token_ids)
    for token in tokens:
        if token.in_accepted_phrase:
            affected.update(unmerge_phrase(conn, document_id, token.id))
    group_starts = {
        token.phrase_start_position
        for token in tokens
        if token.phrase_start_position is not None and not token.in_accepted_phrase
    }

    chosen_ids: list[int] = []
    new_rows: list[dict] = []
    selections: list[tuple] = []
    for token in tokens:
        value = token.match_value
        if value is None:
            spans = furigana_spans or furigana_spans_for_reading(
                token.surface, to_katakana(reading_hiragana)
            )
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
                    headword_reading(token.normalized_form, token.dictionary_form),
                )
                new_rows.append(
                    {
                        "token_id": token.id,
                        "value": original,
                        "selected": False,
                        "ord": len(new_rows),
                    }
                )
            new_rows.append(
                {
                    "token_id": token.id,
                    "value": value,
                    "selected": True,
                    "ord": len(new_rows),
                }
            )
        else:
            chosen_ids.append(token.match_id)
        selections.append((token, value))

    # citation_reading, not the reading itself, since JMDict is keyed by
    # citation form and the two differ for an inflected token. Falls back to
    # "reading" for any option written before citation_reading existed.
    keys = {
        token.id: (
            token.normalized_form,
            value.get("citation_reading", value["reading"]),
        )
        for token, value in selections
    }
    gloss_ids = store_glosses(
        conn,
        plan_glosses(
            conn, [(keys[token.id], token.dictionary_form) for token, _ in selections]
        ),
    )

    # Deselected before anything is selected, for the "one selected row per
    # token" unique index.
    conn.execute(
        text(
            "UPDATE conflicts SET selected = FALSE, selected_at = NULL WHERE token_id = ANY(:token_ids) AND selected"
        ),
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
            text(
                "UPDATE conflicts SET selected = TRUE, selected_at = now() WHERE id = ANY(:ids)"
            ),
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
                    {
                        "id": token.id,
                        "furigana_spans": value["furigana_spans"],
                        "gloss_lookup_id": gloss_ids[keys[token.id]],
                    }
                    for token, value in selections
                ]
            )
        },
    )
    affected.update(_regloss_groups(conn, document_id, list(group_starts)))
    return list(affected)


class WordNotOffered(Exception):
    pass


def pick_piece_word(
    conn, document_id: int, token_ids: list[int], piece: int, idseq: int
) -> None:
    """Make the JMDict entry `idseq` the word that piece `piece` of the gloss
    of each of the document's tokens in `token_ids`, sung in katakana, is:
    one of the words JMDict has with the piece's reading (see word_options),
    in place of the one the gloss guessed (合う for the アイ of アイタイ,
    rather than 会う). The tokens must be ones lock_token_group accepts
    together.

    Raises WordNotOffered if a token isn't sung in katakana, `piece` isn't
    one of its words, or `idseq` isn't a word with the piece's reading."""
    lock_token_group(conn, document_id, token_ids)
    reading = _piece_reading(conn, token_ids, piece)
    if idseq not in {option["idseq"] for option in word_options(conn, reading)}:
        raise WordNotOffered()

    conn.execute(
        text(
            """
            INSERT INTO katakana_picks (token_id, piece, reading, idseq)
            SELECT id, :piece, :reading, :idseq FROM unnest(CAST(:token_ids AS int[])) AS id
            ON CONFLICT (token_id, piece)
                DO UPDATE SET reading = EXCLUDED.reading, idseq = EXCLUDED.idseq
            """
        ),
        {
            "token_ids": token_ids,
            "piece": piece,
            "reading": reading,
            "idseq": idseq,
        },
    )


def piece_word_options(conn, document_id: int, token_id: int, piece: int) -> list[dict]:
    """The words piece `piece` of the gloss of the document's token
    `token_id`, sung in katakana, could be, as pick_piece_word takes them:
    every word JMDict has with the piece's reading (see word_options), the
    one the piece is now marked `current`.

    Raises TokenNotFound if the document has no token `token_id`, and
    WordNotOffered if it isn't sung in katakana or `piece` isn't one of its
    words."""
    row = conn.execute(
        text(
            f"""
            SELECT {KATAKANA_GLOSS_COLUMNS}
            FROM tokens t
            LEFT JOIN gloss_lookups gl ON gl.id = t.gloss_lookup_id
            WHERE t.id = :token_id AND t.document_id = :document_id
            """
        ),
        {"token_id": token_id, "document_id": document_id},
    ).one_or_none()
    if row is None:
        raise TokenNotFound()
    if row.katakana_gloss is None:
        raise WordNotOffered()
    reading = _shared_reading([row.katakana_gloss], piece)
    # The piece's own lookup and its reading's are the same key for a piece
    # that is picked, so one call fetches both.
    shown = picked_katakana_gloss(row)["pieces"][piece]
    reading_key = (reading, reading)
    lookups = gloss_entries(
        conn,
        [(tuple(shown["key"]), shown["alt_lookup_form"]), (reading_key, None)],
    )
    current = piece_current_idseq(
        conn, row.katakana_gloss, row.katakana_picks, piece, lookups
    )
    return [
        {**option, "current": option["idseq"] == current}
        for option in word_options(conn, reading, lookups[reading_key])
    ]


def _piece_reading(conn, token_ids: list[int], piece: int) -> str:
    """The reading, as JMDict keys it, of piece `piece` of the gloss of each
    of `token_ids`, tokens sung in katakana (あう for the アイ of アイタイ).

    Raises WordNotOffered if a token isn't sung in katakana, `piece` isn't
    one of its words, or they don't all read it the same."""
    glosses = (
        conn.execute(
            text(
                f"""
                SELECT gl.entries FROM tokens t
                JOIN gloss_lookups gl ON gl.id = t.gloss_lookup_id
                    AND {KATAKANA_GLOSS_SQL}
                WHERE t.id = ANY(:token_ids)
                """
            ),
            {"token_ids": token_ids},
        )
        .scalars()
        .all()
    )
    # One missing isn't sung in katakana.
    if len(glosses) != len(token_ids):
        raise WordNotOffered()
    return _shared_reading(glosses, piece)


def _shared_reading(glosses: list[dict], piece: int) -> str:
    """The reading, as JMDict keys it, of piece `piece` of each of `glosses`,
    katakana tokens' glosses.

    Raises WordNotOffered if `piece` isn't one of a gloss's words, or they
    don't all read it the same."""
    readings = set()
    for gloss in glosses:
        pieces = gloss["pieces"]
        if piece >= len(pieces) or not is_word_piece(pieces[piece]):
            raise WordNotOffered()
        readings.add(pieces[piece]["key"][1])
    # Tokens spelled alike are glossed with the same pieces today, but
    # nothing before this checks it, so one word is never applied to tokens
    # that read the piece differently.
    if len(readings) != 1:
        raise WordNotOffered()
    [reading] = readings
    return reading


def correct_reading(
    conn, document_id: int, token_id: int, reading_hiragana: str
) -> None:
    """Select a user-supplied pronunciation for a token — for whenever
    Sudachi's own reading is wrong (三股 as みまた instead of さんまた) or
    nothing else offered a fix (no heteronym/split candidates existed, or
    the token is OOV) — as select_reading does."""
    select_reading(conn, document_id, [token_id], reading_hiragana)


def token_reading_options(conn, document_id: int, token_id: int) -> list[dict]:
    """Every reading the document's token `token_id` can be given, one per
    reading, as select_reading takes them: its own options, or else the
    reading it was tokenized with, then every other reading JMDict has for
    its dictionary form. Each says what picking it does, since select_reading
    picks a token's own option over any other with its reading, and whether
    it is one of the token's own (`own`).

    Raises TokenNotFound if the document has no token `token_id`."""
    row = conn.execute(
        text(
            """
            SELECT t.surface, t.reading_katakana, t.furigana_spans, t.furigana_override,
                   t.dictionary_form, t.normalized_form,
                   (SELECT jsonb_agg(c.value ORDER BY c.id) FROM conflicts c
                    WHERE c.token_id = t.id AND c.kind <> ALL(:non_reading_kinds)) AS own
            FROM tokens t WHERE t.id = :token_id AND t.document_id = :document_id
            """
        ),
        {
            "token_id": token_id,
            "document_id": document_id,
            "non_reading_kinds": list(NON_READING_KINDS),
        },
    ).one_or_none()
    if row is None:
        raise TokenNotFound()
    # A token's own options start with the reading it was tokenized with
    # (create_conflicts, select_reading), so that's only built when it has
    # none, the same way.
    own = row.own or [
        conflict_option_value(
            to_hiragana(row.reading_katakana),
            row.furigana_override or row.furigana_spans,
            headword_reading(row.normalized_form, row.dictionary_form),
        )
    ]
    options: dict[str, dict] = {}
    for value in own:
        options.setdefault(value["reading"], {**value, "own": True})
    for value in alternate_reading_options(
        row.surface, row.reading_katakana, row.dictionary_form, row.normalized_form
    ):
        options.setdefault(value["reading"], {**value, "own": False})
    return list(options.values())
