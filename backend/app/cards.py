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
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

from app.conflicts import NON_READING_KINDS, TokenNotFound
from app.glosses import (
    GlossKey,
    own_gloss_key,
    piece_lookups,
    piece_pos_major,
    plan_glosses,
    shown_spellings,
    store_glosses,
)
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


# Joins `study_cards c` to the keys in a :keys parameter from card_keys_param.
# Its columns are prefixed so an unqualified CARD_COLUMNS stays unambiguous.
CARD_KEYS_JOIN_SQL = """
    JOIN jsonb_to_recordset(CAST(:keys AS JSONB))
        AS k(key_kind text, key_lookup_form text, key_reading text)
      ON c.kind = k.key_kind AND c.lookup_form = k.key_lookup_form
     AND c.reading IS NOT DISTINCT FROM k.key_reading
"""


def card_keys_param(keys: Iterable[CardKey]) -> str:
    """`keys` as the :keys parameter CARD_KEYS_JOIN_SQL reads."""
    return json.dumps(
        [
            {
                "key_kind": k.kind,
                "key_lookup_form": k.lookup_form,
                "key_reading": k.reading,
            }
            for k in keys
        ]
    )


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


@dataclass
class CardTokens:
    """A word or grammar term a card can be for, where a document has it."""

    key: CardKey
    # A second spelling to look the word's gloss up under (see plan_glosses).
    alt_lookup_form: str | None
    # The tokens it's written with: all of an accepted phrase's, else one.
    tokens: list
    # Set only for one of the words of a token sung in katakana: where in
    # the token it is, as [begin, end) offsets, how its gloss writes it (声
    # for コエ), and the part of speech its senses are ranked for.
    span: tuple[int, int] | None = None
    written_as: str | None = None
    pos_major: str | None = None


class NotStudyable(Exception):
    pass


def _token_rows(conn, document_ids: list[int]) -> list:
    """The documents' tokens, each document's in order, each with its
    selected reading, for the first token of an accepted phrase, the phrase,
    and for a token sung in katakana, its gloss as the hiragana's words (see
    app.katakana)."""
    return conn.execute(
        text(
            """
            SELECT t.id, t.document_id, t.position, t.char_begin, t.char_end,
                   t.normalized_form, t.dictionary_form, t.part_of_speech,
                   t.needs_review, t.review_reason, t.gloss_ignored, t.phrase_start_position,
                   COALESCE(rc.value ->> 'citation_reading', rc.value ->> 'reading') AS selected_reading,
                   pc.value AS accepted_phrase,
                   kg.entries AS katakana_gloss
            FROM tokens t
            -- A token has at most one selected conflict, so neither join
            -- repeats it. A phrase's value has a reading too, so only reading
            -- kinds count as a selected reading.
            LEFT JOIN conflicts rc ON rc.token_id = t.id AND rc.selected AND rc.kind <> ALL(:non_reading_kinds)
            LEFT JOIN conflicts pc ON pc.token_id = t.id AND pc.selected AND pc.kind = 'phrase'
            -- A group's members share the group's gloss, which is never one
            -- of these, so only a token on its own has one.
            LEFT JOIN gloss_lookups kg ON kg.id = t.gloss_lookup_id
                AND kg.source = 'composite' AND kg.entries ? 'looked_up_as'
            WHERE t.document_id = ANY(:document_ids)
            ORDER BY t.document_id, t.position
            """
        ),
        {"document_ids": document_ids, "non_reading_kinds": list(NON_READING_KINDS)},
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


def document_units(conn, document_id: int) -> list[list]:
    """The document's tokens in order, grouped into what's glossed together."""
    return _units(_token_rows(conn, [document_id]))


def units_by_document(conn, document_ids: list[int]) -> dict[int, list[list]]:
    """As document_units, for each of the documents that has tokens."""
    rows_by_document: dict[int, list] = {}
    for row in _token_rows(conn, document_ids):
        rows_by_document.setdefault(row.document_id, []).append(row)
    return {document_id: _units(rows) for document_id, rows in rows_by_document.items()}


def _own_word(row, explicit: bool) -> tuple[CardKey, str | None] | None:
    """The word token `row` is glossed as on its own, with its alternate
    spelling, or None if it isn't one to study. `explicit` as for
    _unit_word."""
    if is_grammar_word(row.part_of_speech):
        return None
    if not explicit and (
        row.gloss_ignored
        or (row.needs_review and row.review_reason in _GUESSED_READING_REASONS)
    ):
        return None
    key = own_gloss_key(
        row.normalized_form,
        row.dictionary_form,
        row.part_of_speech,
        row.selected_reading,
    )
    if key is None:
        return None
    return CardKey("recognition", *key), row.dictionary_form


def _word_token_count(unit: list) -> int:
    """How many of `unit`'s tokens its word is written with: all of an
    accepted phrase's, or the one a word on its own or a predicate group's
    head is."""
    phrase = unit[0].accepted_phrase
    if phrase is None:
        return 1
    return phrase.get("phrase_token_count", len(unit))


def _attached_grammar(unit: list) -> list:
    """The tokens of `unit` that are grammar attached to its word, and have
    an explanation of their own."""
    # The particles inside a phrase (この期に及んで's に) are part of the
    # headword, not grammar attached to it.
    return [
        row
        for row in unit[_word_token_count(unit) :]
        if has_grammar_note(row.normalized_form)
    ]


def _unit_word(unit: list, explicit: bool) -> CardTokens | None:
    """The word `unit` is studied as, or None if there isn't one to study.
    `explicit` for a word the user chose to add, which overrides their
    having marked it as needing no gloss, and its reading still being a
    guess."""
    head = unit[0]
    phrase = head.accepted_phrase
    if phrase is not None:
        tokens = unit[: _word_token_count(unit)]
        if not explicit and any(row.gloss_ignored for row in tokens):
            return None
        # Glossed under the headword alone, as _apply_phrase_selection does.
        key = CardKey("recognition", phrase["lookup_form"], phrase["reading"])
        return CardTokens(key, None, tokens)
    # A predicate group's head is studied as the word it is on its own, not
    # as the group's composite gloss.
    word = _own_word(head, explicit)
    return CardTokens(*word, [head]) if word else None


def katakana_lookups(conn, units: Iterable[list]) -> dict[GlossKey, tuple]:
    """The lookups the pieces of the katakana tokens in `units` (see _units)
    are glossed from, as unit_card_tokens takes them. One that isn't cached
    is looked up and cached first."""
    return piece_lookups(
        conn,
        [unit[0].katakana_gloss for unit in units if unit[0].katakana_gloss],
    )


def _katakana_card_tokens(row, lookups: dict[GlossKey, tuple]) -> list[CardTokens]:
    """The words and grammar terms token `row`, sung in katakana, is glossed
    as (ココロノコエ as 心の声), given its pieces' `lookups`. A word is the
    one its gloss writes it as, so アイタイ's あう is 会う, which the gloss
    guesses from the sense it shows first."""
    gloss = row.katakana_gloss
    # Worked out here rather than stored, as on the page, so a change to how
    # a gloss ranks or spells its pieces reaches every card key.
    spellings = shown_spellings(gloss, lookups)
    if spellings is None:
        return []
    pieces = gloss["pieces"]
    unit_sizes = Counter(piece["unit"] for piece in pieces)
    found = []
    for piece, spelling in zip(pieces, spellings, strict=True):
        if piece["normalized_form"] is None:
            # Every piece but a grammar word's has a key. Its reading is the
            # word's whichever way it's written.
            key = CardKey("recognition", spelling, piece["key"][1])
        # Grammar between two words (the の of 心の声) is a unit of its own,
        # and like a particle outside a group, gives nothing. A helper verb
        # has a key as well, but counts as grammar, as in _attached_grammar.
        elif unit_sizes[piece["unit"]] > 1 and has_grammar_note(
            piece["normalized_form"]
        ):
            key = CardKey("grammar", piece["normalized_form"], None)
        else:
            continue
        found.append(
            CardTokens(
                key,
                piece["alt_lookup_form"],
                [row],
                span=tuple(piece["span"]),
                written_as=spelling,
                pos_major=piece_pos_major(piece),
            )
        )
    return found


def unit_card_tokens(
    unit: list,
    explicit: bool = True,
    katakana: dict[GlossKey, tuple] | None = None,
) -> list[CardTokens]:
    """The word `unit` is studied as (see _unit_word), if any, then the
    grammar terms attached to it, each with the tokens it's written with.
    The default finds them as document_card_keys does.

    A token sung in katakana gives the words and grammar its gloss splits it
    into, given its pieces' lookups as `katakana` (see katakana_lookups), but
    only by default: which kanji katakana stands for is a guess (コエ could
    be 声 or 越え), so it links to cards but never makes one."""
    if unit[0].katakana_gloss is not None:
        if not explicit or katakana is None:
            return []
        return _katakana_card_tokens(unit[0], katakana)
    word = _unit_word(unit, explicit)
    return ([word] if word else []) + [
        CardTokens(CardKey("grammar", row.normalized_form, None), None, [row])
        for row in _attached_grammar(unit)
    ]


def gloss_sources(
    conn, requests: Iterable[tuple[GlossKey, str | None]]
) -> dict[GlossKey, str]:
    """The source of each requested key's gloss, each paired with an
    alternate spelling as plan_glosses takes it. A key that isn't cached is
    looked up and cached first: the cache can be emptied underneath a card
    at any time."""
    plan = plan_glosses(conn, list(requests))
    store_glosses(conn, plan)
    return plan.sources()


def _studyable(conn, words: list[tuple[CardKey, str | None]]) -> set[CardKey]:
    """Those of `words` glossed from a JMDict headword. An English word, or a
    compound or katakana fallback, has a gloss that explains it rather than
    defines it, so there's nothing to test."""
    sources = gloss_sources(
        conn, [((key.lookup_form, key.reading), alt) for key, alt in words]
    )
    return {
        key for key, _ in words if sources[(key.lookup_form, key.reading)] == "jmdict"
    }


def harvest(conn, units: list[list], user_id: int) -> list[HarvestedWord]:
    """Every word and grammar term of a document's `units` (see _units) that
    becomes a card when enrolled, in order of first occurrence, except those
    the user `user_id` already has a card for, removed ones included.

    A word is left out if it's a particle or auxiliary, if it was marked as
    needing no gloss, or if its reading is still an unreviewed guess, since
    review history built on it would belong to a different word once the
    reading is corrected. A predicate group's head is a word of its own; the
    grammar attached to it, or to a phrase, gives grammar terms, when they
    have an explanation of their own."""
    found: dict[CardKey, HarvestedWord] = {}
    for unit in units:
        for card in unit_card_tokens(unit, explicit=False):
            if card.key in found:
                found[card.key].occurrences += 1
            else:
                found[card.key] = HarvestedWord(
                    card.key, card.alt_lookup_form, 1, unit[0].position
                )

    # Dropped before _studyable, which would look up (and maybe fetch) the
    # gloss of every word the user already has a card for.
    carded = _carded_keys(conn, user_id, list(found))
    wanted = [w for w in found.values() if w.key not in carded]
    studyable = _studyable(
        conn, [(w.key, w.alt_lookup_form) for w in wanted if w.key.kind != "grammar"]
    )
    return [w for w in wanted if w.key.kind == "grammar" or w.key in studyable]


def document_card_keys(conn, units: list[list]) -> set[CardKey]:
    """The key of every word and grammar term in a document's `units` (see
    _units): which cards belong to the song, if the user has them. Unlike
    harvest, it counts a word marked as needing no gloss, or read as a guess,
    since a card for one can only exist because the user added it by hand."""
    lookups = katakana_lookups(conn, units)
    return {
        card.key for unit in units for card in unit_card_tokens(unit, katakana=lookups)
    }


def _carded_keys(conn, user_id: int, keys: list[CardKey]) -> set[CardKey]:
    """Those of `keys` the user has a card for, removed ones included."""
    if not keys:
        return set()
    return {
        CardKey(row.kind, row.lookup_form, row.reading)
        for row in conn.execute(
            text(
                f"""
                SELECT c.kind, c.lookup_form, c.reading
                FROM study_cards c {CARD_KEYS_JOIN_SQL}
                WHERE c.user_id = :user_id
                """
            ),
            {"user_id": user_id, "keys": card_keys_param(keys)},
        )
    }


def song_card_keys(
    conn, user_id: int, document_id: int, units: list[list], enroll_limit: int
) -> set[CardKey]:
    """The key of every word and grammar term in the document of `units`
    (see _units), after giving the user cards for up to `enroll_limit` of
    its new words (none if it's zero or less)."""
    if enroll_limit > 0:
        _enroll_units(conn, user_id, document_id, units, enroll_limit)
    return document_card_keys(conn, units)


def enroll_new_words(
    conn, user_id: int, document_id: int, limit: int | None = None
) -> list[int]:
    """As _enroll_units, reading the document's units itself."""
    return _enroll_units(
        conn, user_id, document_id, document_units(conn, document_id), limit
    )


def _enroll_units(
    conn, user_id: int, document_id: int, units: list[list], limit: int | None
) -> list[int]:
    """Give the user a card for each of up to `limit` (all if None) of the
    harvested words in `units`, the document's (see _units), that they have
    no card for yet, the most often sung first, and return the new cards'
    ids. A card they removed still counts as one they have: only adding it
    by hand restores it."""
    words = sorted(
        harvest(conn, units, user_id),
        key=lambda w: (-w.occurrences, w.first_position),
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
            for unit in document_units(conn, document_id)
            if any(row.id == token_id for row in unit)
        ),
        None,
    )
    if unit is None:
        raise TokenNotFound()
    word = _unit_word(unit, explicit=True)
    if word is None or not _studyable(conn, [(word.key, word.alt_lookup_form)]):
        raise NotStudyable()

    key, alt = word.key, word.alt_lookup_form
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
