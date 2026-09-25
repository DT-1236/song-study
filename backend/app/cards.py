"""Study cards: which of a document's words become cards (the harvest), and
enrolling them for a user.

A card names what it tests by value (see migration 0018): a word by the gloss
key its tokens are glossed under, which makes the resolved reading half of
its identity (辛い read からい and read つらい are two cards), or a grammar
term by its normalized form. Which documents a card belongs to is never
stored: it's whichever documents have a token that harvests to it now.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from app.conflicts import NON_READING_KINDS, TokenNotFound
from app.glosses import GlossKey, own_gloss_key, plan_glosses, store_glosses
from app.grammar import has_grammar_note, is_grammar_word

CardKind = Literal["recognition", "grammar"]

# Review reasons that mean a token's reading, and so which word it's glossed
# as, is still Sudachi's guess. A no_kana_anchor token's reading is certain;
# only how its furigana splits across the kanji isn't.
_GUESSED_READING_REASONS = ("heteronym", "oov")

CARD_COLUMNS = "id, kind, lookup_form, reading, suspended, due, first_seen_document_id"


@dataclass(frozen=True)
class CardKey:
    """What a card tests: a word, by its gloss key, or a grammar term, with
    no reading."""

    kind: CardKind
    lookup_form: str
    reading: str | None


@dataclass
class HarvestedWord:
    """A word or grammar term of a document that becomes a card when
    enrolled."""

    key: CardKey
    # A second spelling to look the word's gloss up under (see plan_glosses).
    alt_lookup_form: str | None
    # A merged group counts once.
    occurrences: int
    first_position: int


class NotStudyable(Exception):
    pass


def _token_rows(conn, document_id: int) -> list:
    """The document's tokens in order, each with its selected reading and,
    for the first token of an accepted phrase, the phrase."""
    return conn.execute(
        text(
            """
            SELECT t.id, t.position, t.normalized_form, t.dictionary_form, t.part_of_speech,
                   t.needs_review, t.review_reason, t.gloss_ignored, t.phrase_start_position,
                   COALESCE(rc.value ->> 'citation_reading', rc.value ->> 'reading') AS selected_reading,
                   pc.value AS accepted_phrase
            FROM tokens t
            -- A token has at most one selected conflict, so neither join
            -- repeats it. A phrase's value has a reading too, so only reading
            -- kinds count as a selected reading.
            LEFT JOIN conflicts rc ON rc.token_id = t.id AND rc.selected AND rc.kind <> ALL(:non_reading_kinds)
            LEFT JOIN conflicts pc ON pc.token_id = t.id AND pc.selected AND pc.kind = 'phrase'
            WHERE t.document_id = :document_id
            ORDER BY t.position
            """
        ),
        {"document_id": document_id, "non_reading_kinds": list(NON_READING_KINDS)},
    ).all()


def _units(rows: list) -> list[list]:
    """Token `rows`, in order, as what's glossed together: each token on its
    own, or all of a merged group's."""
    units: list[list] = []
    for row in rows:
        # A group's tokens are consecutive.
        if (
            row.phrase_start_position is not None
            and units
            and units[-1][0].phrase_start_position == row.phrase_start_position
        ):
            units[-1].append(row)
        else:
            units.append([row])
    return units


def _own_word(row, explicit: bool) -> tuple[CardKey, str | None] | None:
    """The word token `row` is glossed as on its own, with its alternate
    spelling, or None if it isn't one to study. `explicit` as for
    _unit_cards."""
    if is_grammar_word(row.part_of_speech):
        return None
    if not explicit and (
        row.gloss_ignored
        or (row.needs_review and row.review_reason in _GUESSED_READING_REASONS)
    ):
        return None
    key = own_gloss_key(row.normalized_form, row.part_of_speech, row.selected_reading)
    if key is None:
        return None
    return CardKey("recognition", *key), row.dictionary_form


def _unit_cards(
    unit: list, explicit: bool
) -> tuple[tuple[CardKey, str | None] | None, list[CardKey]]:
    """The word `unit` is studied as, with its alternate spelling (None if
    there isn't one to study), and the grammar terms attached to it.
    `explicit` for a word the user chose to add, which overrides their
    having marked it as needing no gloss, and its reading still being a
    guess."""
    head = unit[0]
    phrase = head.accepted_phrase
    if phrase is not None:
        phrase_token_count = phrase.get("phrase_token_count", len(unit))
        # Glossed under the headword alone, as _apply_phrase_selection does.
        word = (
            CardKey("recognition", phrase["lookup_form"], phrase["reading"]),
            None,
        )
        if not explicit and any(row.gloss_ignored for row in unit[:phrase_token_count]):
            word = None
        # The particles inside a phrase (この期に及んで's に) are part of the
        # headword, not grammar attached to it.
        attached = unit[phrase_token_count:]
    else:
        # A predicate group's head is studied as the word it is on its own,
        # not as the group's composite gloss.
        word = _own_word(head, explicit)
        attached = unit[1:]
    grammar = [
        CardKey("grammar", row.normalized_form, None)
        for row in attached
        if has_grammar_note(row.normalized_form)
    ]
    return word, grammar


def gloss_rows(conn, requests: Iterable[tuple[GlossKey, str | None]]) -> dict:
    """The gloss_lookups row (lookup_form, reading, entries, source) of each
    requested key, each paired with an alternate spelling as plan_glosses
    takes it. A key that isn't cached is looked up and cached first: the
    cache can be emptied underneath a card at any time."""
    ids = store_glosses(conn, plan_glosses(conn, list(requests)))
    rows = conn.execute(
        text(
            """
            SELECT lookup_form, reading, entries, source FROM gloss_lookups
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": list(ids.values())},
    )
    return {(row.lookup_form, row.reading): row for row in rows}


def _studyable(conn, words: list[tuple[CardKey, str | None]]) -> set[CardKey]:
    """Those of `words` glossed from a JMDict headword. An English word, or a
    compound or katakana fallback, has a gloss that explains it rather than
    defines it, so there's nothing to test."""
    rows = gloss_rows(
        conn, [((key.lookup_form, key.reading), alt) for key, alt in words]
    )
    return {
        key
        for key, _ in words
        if (row := rows[(key.lookup_form, key.reading)]).source == "jmdict"
        and row.entries
    }


def harvest(conn, document_id: int) -> list[HarvestedWord]:
    """Every word and grammar term of the document that becomes a card when
    enrolled, in order of first occurrence.

    A word is left out if it's a particle or auxiliary, if it was marked as
    needing no gloss, or if its reading is still an unreviewed guess, since
    review history built on it would belong to a different word once the
    reading is corrected. A predicate group's head is a word of its own; the
    grammar attached to it, or to a phrase, gives grammar terms, when they
    have an explanation of their own."""
    found: dict[CardKey, HarvestedWord] = {}
    for unit in _units(_token_rows(conn, document_id)):
        word, grammar = _unit_cards(unit, explicit=False)
        for key, alt in [*([word] if word else []), *((key, None) for key in grammar)]:
            if key in found:
                found[key].occurrences += 1
            else:
                found[key] = HarvestedWord(key, alt, 1, unit[0].position)

    studyable = _studyable(
        conn,
        [(w.key, w.alt_lookup_form) for w in found.values() if w.key.kind != "grammar"],
    )
    return [w for w in found.values() if w.key.kind == "grammar" or w.key in studyable]


def enroll_new_words(
    conn, user_id: int, document_id: int, limit: int | None = None
) -> list[int]:
    """Give the user a card for each of up to `limit` of the document's
    harvested words they have no card for yet, the most often sung first,
    and return the new cards' ids. A card they removed still counts as one
    they have: only adding it by hand restores it."""
    words = sorted(
        harvest(conn, document_id), key=lambda w: (-w.occurrences, w.first_position)
    )
    if not words:
        return []
    return (
        conn.execute(
            text(
                """
                INSERT INTO study_cards (
                    user_id, kind, lookup_form, reading, alt_lookup_form, first_seen_document_id
                )
                SELECT :user_id, w.kind, w.lookup_form, w.reading, w.alt_lookup_form, :document_id
                FROM jsonb_to_recordset(CAST(:words AS JSONB))
                    AS w(ord int, kind text, lookup_form text, reading text, alt_lookup_form text)
                WHERE NOT EXISTS (
                    SELECT 1 FROM study_cards c
                    WHERE c.user_id = :user_id AND c.kind = w.kind AND c.lookup_form = w.lookup_form
                      AND c.reading IS NOT DISTINCT FROM w.reading
                )
                ORDER BY w.ord
                LIMIT :limit
                -- A concurrent enrollment of the same word wins; this one
                -- then creates one card fewer than `limit`.
                ON CONFLICT ON CONSTRAINT study_cards_word_key DO NOTHING
                RETURNING id
                """
            ),
            {
                "user_id": user_id,
                "document_id": document_id,
                "limit": limit,
                "words": json.dumps(
                    [
                        {
                            "ord": i,
                            "kind": w.key.kind,
                            "lookup_form": w.key.lookup_form,
                            "reading": w.key.reading,
                            "alt_lookup_form": w.alt_lookup_form,
                        }
                        for i, w in enumerate(words)
                    ]
                ),
            },
        )
        .scalars()
        .all()
    )


def enroll_token(conn, user_id: int, document_id: int, token_id: int):
    """The user's card row for the word `token_id` is part of — for a
    predicate group, the word the group is built on — created if they have
    none, or restored with its history if they removed it. Unlike
    enroll_new_words, this takes a word marked as needing no gloss, or read
    as a guess, since adding it is an explicit choice.

    Raises TokenNotFound if the document has no token `token_id`, and
    NotStudyable if it isn't part of a word glossed from a JMDict
    headword."""
    unit = next(
        (
            unit
            for unit in _units(_token_rows(conn, document_id))
            if any(row.id == token_id for row in unit)
        ),
        None,
    )
    if unit is None:
        raise TokenNotFound()
    word, _ = _unit_cards(unit, explicit=True)
    if word is None or not _studyable(conn, [word]):
        raise NotStudyable()

    key, alt = word
    return conn.execute(
        text(
            f"""
            INSERT INTO study_cards (
                user_id, kind, lookup_form, reading, alt_lookup_form, first_seen_document_id
            )
            VALUES (:user_id, :kind, :lookup_form, :reading, :alt_lookup_form, :document_id)
            ON CONFLICT ON CONSTRAINT study_cards_word_key DO UPDATE SET suspended = FALSE
            RETURNING {CARD_COLUMNS}
            """
        ),
        {
            "user_id": user_id,
            "kind": key.kind,
            "lookup_form": key.lookup_form,
            "reading": key.reading,
            "alt_lookup_form": alt,
            "document_id": document_id,
        },
    ).one()
