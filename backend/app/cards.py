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

from fsrs import State
from sqlalchemy import text

from app.conflicts import NON_READING_KINDS, TokenNotFound
from app.glosses import (
    KATAKANA_GLOSS_COLUMNS,
    GlossKey,
    gloss_entries,
    is_word_piece,
    own_gloss_key,
    picked_katakana_gloss,
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

# A card is mature once its memory is expected to last this many days,
# Anki's convention.
MATURE_STABILITY_DAYS = 21


def is_mature(state: int, stability: float | None) -> bool:
    """Whether a card in FSRS `state` with `stability` (in days) is mature."""
    return (
        state == State.Review
        and stability is not None
        and stability >= MATURE_STABILITY_DAYS
    )


CARD_COLUMNS = (
    "id, kind, lookup_form, reading, idseq, suspended, due, first_seen_document_id"
)


@dataclass(frozen=True)
class CardKey:
    """What a card tests: a word, by its gloss key, or a grammar term, with
    no reading. A word picked for a piece of katakana is also keyed by its
    JMDict entry, `idseq`, when another is read and written alike (元 read
    もと, "origin" and "former")."""

    kind: CardKind
    lookup_form: str
    reading: str | None
    idseq: int | None = None

    @classmethod
    def of(cls, row) -> CardKey:
        """The key of a study_cards `row`."""
        return cls(row.kind, row.lookup_form, row.reading, row.idseq)


# Joins `study_cards c` to the keys in a :keys parameter from card_keys_param.
# Its columns are prefixed so an unqualified CARD_COLUMNS stays unambiguous.
CARD_KEYS_JOIN_SQL = """
    JOIN jsonb_to_recordset(CAST(:keys AS JSONB))
        AS k(key_kind text, key_lookup_form text, key_reading text, key_idseq int)
      ON c.kind = k.key_kind AND c.lookup_form = k.key_lookup_form
     AND c.reading IS NOT DISTINCT FROM k.key_reading
     AND c.idseq IS NOT DISTINCT FROM k.key_idseq
"""


def card_keys_param(keys: Iterable[CardKey]) -> str:
    """`keys` as the :keys parameter CARD_KEYS_JOIN_SQL reads."""
    return json.dumps(
        [
            {
                "key_kind": k.kind,
                "key_lookup_form": k.lookup_form,
                "key_reading": k.reading,
                "key_idseq": k.idseq,
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
    # How a card's word can be corrected from a line it's on: "reading" for
    # a word written in kanji, by picking another reading of its token;
    # "word" for a word sung in katakana, by picking another word for its
    # piece. Never a grammar term, nor an accepted phrase, which picking a
    # reading of one of its tokens would split.
    correction: Literal["reading", "word"] | None = None
    # For a word or grammar term that's one piece of a composite gloss (a
    # katakana token's or a group's), which piece it is.
    piece: int | None = None
    # Set only for one of the words of a token sung in katakana: where in the
    # token it is, as [begin, end) offsets, how its gloss writes it (声 for
    # コエ), and the part of speech its senses are ranked for.
    span: tuple[int, int] | None = None
    written_as: str | None = None
    pos_major: str | None = None


class NotStudyable(Exception):
    pass


def _token_rows(conn, document_ids: list[int], token_id: int | None = None) -> list:
    """The documents' tokens (with `token_id`, only its unit's), each
    document's in order, each with its selected reading, for the first token
    of an accepted phrase, the phrase, and for a token sung in katakana, its
    gloss as the hiragana's words (see app.katakana) and the words the user
    picked for its pieces, and for a member of a group, how many pieces the
    group's gloss has."""
    return conn.execute(
        text(
            f"""
            SELECT t.id, t.document_id, t.position, t.char_begin, t.char_end,
                   t.surface, t.normalized_form, t.dictionary_form, t.part_of_speech,
                   t.needs_review, t.review_reason, t.gloss_ignored, t.phrase_start_position,
                   COALESCE(t.furigana_override, t.furigana_spans) AS furigana,
                   COALESCE(rc.value ->> 'citation_reading', rc.value ->> 'reading') AS selected_reading,
                   pc.value AS accepted_phrase,
                   -- A group's members share the group's gloss, which is never
                   -- a katakana one, so only a token on its own has one.
                   {KATAKANA_GLOSS_COLUMNS},
                   CASE WHEN t.phrase_start_position IS NOT NULL
                       THEN jsonb_array_length(gl.entries -> 'pieces') END AS group_piece_count
            FROM tokens t
            -- A token has at most one selected conflict, so neither join
            -- repeats it. A phrase's value has a reading too, so only reading
            -- kinds count as a selected reading.
            LEFT JOIN conflicts rc ON rc.token_id = t.id AND rc.selected AND rc.kind <> ALL(:non_reading_kinds)
            LEFT JOIN conflicts pc ON pc.token_id = t.id AND pc.selected AND pc.kind = 'phrase'
            LEFT JOIN gloss_lookups gl ON gl.id = t.gloss_lookup_id AND gl.source = 'composite'
            WHERE t.document_id = ANY(:document_ids)
                AND (:token_id IS NULL OR t.id = :token_id OR t.phrase_start_position = (
                    SELECT s.phrase_start_position FROM tokens s
                    WHERE s.id = :token_id AND s.document_id = ANY(:document_ids)
                ))
            ORDER BY t.document_id, t.position
            """
        ),
        {
            "document_ids": document_ids,
            "token_id": token_id,
            "non_reading_kinds": list(NON_READING_KINDS),
        },
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
    key = own_gloss_key(row, row.selected_reading)
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


def _attached_grammar(unit: list) -> list[tuple[int | None, object]]:
    """The tokens of `unit` that are grammar attached to its word, and have
    an explanation of their own, each with which piece of the unit's gloss
    it is, or None if that gloss isn't a composite."""
    # The particles inside a phrase (この期に及んで's に) are part of the
    # headword, not grammar attached to it.
    start = _word_token_count(unit)
    count = unit[0].group_piece_count
    return [
        # A group's gloss ends with one piece per token after its word (see
        # glosses._group_pieces).
        (None if count is None else count - (len(unit) - index), row)
        for index, row in enumerate(unit[start:], start)
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
    return CardTokens(*word, [head], correction="reading") if word else None


def katakana_lookups(conn, units: Iterable[list]) -> dict[GlossKey, tuple]:
    """The lookups the pieces of the katakana tokens in `units` (see _units)
    are glossed from, and those of the cards of the words picked for them,
    as unit_card_tokens takes them. One that isn't cached is looked up and
    cached first."""
    glosses = [
        picked_katakana_gloss(unit[0]) for unit in units if unit[0].katakana_gloss
    ]
    lookups = piece_lookups(conn, glosses)
    # A picked word's card key is spelled as its entry is, which only the
    # piece's own lookup says.
    picked = {
        _word_gloss_key(piece, spelling)
        for gloss in glosses
        if any("idseq" in piece for piece in gloss["pieces"])
        for piece, spelling in zip(
            gloss["pieces"], shown_spellings(gloss, lookups), strict=True
        )
        if "idseq" in piece
    }
    return lookups | gloss_entries(
        conn, [(key, None) for key in picked - lookups.keys()]
    )


def _word_gloss_key(piece: dict, spelling: str) -> GlossKey:
    """The gloss key of a card for word `piece` of a katakana token's gloss,
    shown as `spelling`: its reading is the word's whichever way it's
    written."""
    return (spelling, piece["key"][1])


def _card_entry(
    piece: dict, key: GlossKey, lookups: dict[GlossKey, tuple]
) -> int | None:
    """The JMDict entry a card for word `piece`, a katakana token's, under
    gloss `key` is keyed by: the one picked for it, if `key`'s lookup has
    others, else none. A pick that the card's spelling and reading already
    say is the same card as the word unpicked or written in kanji."""
    if "idseq" not in piece:
        return None
    entries, source = lookups[key]
    if source != "jmdict" or all(e["idseq"] == piece["idseq"] for e in entries):
        return None
    return piece["idseq"]


def _katakana_card_tokens(row, lookups: dict[GlossKey, tuple]) -> list[CardTokens]:
    """The words and grammar terms token `row`, sung in katakana, is glossed
    as (ココロノコエ as 心の声), given its pieces' `lookups`. A word is the
    one the user picked for its piece, or else the one its gloss writes it
    as, so アイタイ's あう is 会う, which the gloss guesses from the sense it
    shows first."""
    gloss = picked_katakana_gloss(row)
    # Worked out here rather than stored, as on the page, so a change to how
    # a gloss ranks or spells its pieces reaches every card key.
    spellings = shown_spellings(gloss, lookups)
    if spellings is None:
        return []
    pieces = gloss["pieces"]
    found = []
    for index, (piece, spelling) in enumerate(zip(pieces, spellings, strict=True)):
        if is_word_piece(piece):
            gloss_key = _word_gloss_key(piece, spelling)
            key = CardKey(
                "recognition", *gloss_key, _card_entry(piece, gloss_key, lookups)
            )
        # Grammar between two words (the の of 心の声) is a unit of its own,
        # and like a particle outside a group, gives nothing. A helper verb
        # has a key as well, but counts as grammar, as in _attached_grammar.
        elif piece["attached"] and has_grammar_note(piece["normalized_form"]):
            key = CardKey("grammar", piece["normalized_form"], None)
        else:
            continue
        found.append(
            CardTokens(
                key,
                piece["alt_lookup_form"],
                [row],
                correction="word" if key.kind == "recognition" else None,
                piece=index,
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
        CardTokens(
            CardKey("grammar", row.normalized_form, None), None, [row], piece=piece
        )
        for piece, row in _attached_grammar(unit)
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
    """Those of `words` with something to test: every grammar term, which has
    an explanation of its own, and the words glossed from a JMDict headword.
    An English word, or a compound or katakana fallback, has a gloss that
    explains it rather than defines it."""
    sources = gloss_sources(
        conn,
        [
            ((key.lookup_form, key.reading), alt)
            for key, alt in words
            if key.kind != "grammar"
        ],
    )
    return {
        key
        for key, _ in words
        if key.kind == "grammar" or sources[(key.lookup_form, key.reading)] == "jmdict"
    }


def _found_words(units: list[list]) -> dict[CardKey, HarvestedWord]:
    """Every word and grammar term of a document's `units` (see _units) that
    could become a card, by key, in order of first occurrence."""
    found: dict[CardKey, HarvestedWord] = {}
    for unit in units:
        for card in unit_card_tokens(unit, explicit=False):
            if card.key in found:
                found[card.key].occurrences += 1
            else:
                found[card.key] = HarvestedWord(
                    card.key, card.alt_lookup_form, 1, unit[0].position
                )
    return found


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
    return song_words(conn, units, user_id).unenrolled


@dataclass
class SongWords:
    """The words and grammar terms a song gives cards, as harvest finds
    them, by whether the user has a card for each yet."""

    # Each with its card's row (CARD_COLUMNS and its schedule).
    enrolled: list[tuple[HarvestedWord, object]]
    unenrolled: list[HarvestedWord]


def _user_cards(
    conn, user_id: int, keys: Iterable[CardKey], extra_columns: str = ""
) -> dict[CardKey, object]:
    """The user's cards with any of `keys`, removed or not, by key: rows of
    CARD_COLUMNS and `extra_columns`, a list of `c.` columns led by a
    comma."""
    rows = conn.execute(
        text(
            f"""
            SELECT {CARD_COLUMNS}{extra_columns} FROM study_cards c {CARD_KEYS_JOIN_SQL}
            WHERE c.user_id = :user_id
            """
        ),
        {"user_id": user_id, "keys": card_keys_param(keys)},
    )
    return {CardKey.of(row): row for row in rows}


def song_words(conn, units: list[list], user_id: int) -> SongWords:
    """songs_words for the one document of `units` (see _units)."""
    [words] = songs_words(conn, [units], user_id)
    return words


def songs_words(conn, songs: list[list[list]], user_id: int) -> list[SongWords]:
    """What each of `songs`, a document's units (see _units) each, gives the
    user's cards, in the same order: the words they have a card for and the
    ones harvest would enroll. A word whose card they removed is in neither,
    as it's no longer part of what they study."""
    found = [_found_words(units) for units in songs]
    rows = _user_cards(
        conn,
        user_id,
        {key for words in found for key in words},
        ", c.state, c.step, c.stability, c.difficulty, c.last_review",
    )
    wanted = [[w for w in words.values() if w.key not in rows] for words in found]
    # One gloss plan for every song. A word several songs share is planned
    # with the first one's alternate spelling, as it would be if each song
    # were planned in turn, the later ones finding it cached by the first.
    studyable = _studyable(
        conn, [(w.key, w.alt_lookup_form) for song in wanted for w in song]
    )
    return [
        SongWords(
            [
                (word, rows[word.key])
                for word in words.values()
                if word.key in rows and not rows[word.key].suspended
            ],
            [w for w in song if w.key in studyable],
        )
        for words, song in zip(found, wanted, strict=True)
    ]


def document_card_keys(conn, units: list[list]) -> set[CardKey]:
    """The key of every word and grammar term in a document's `units` (see
    _units): which cards belong to the song, if the user has them. Unlike
    harvest, it counts a word marked as needing no gloss, or read as a guess,
    since a card for one can only exist because the user added it by hand."""
    lookups = katakana_lookups(conn, units)
    return {
        card.key for unit in units for card in unit_card_tokens(unit, katakana=lookups)
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
                    user_id, kind, lookup_form, reading, idseq, alt_lookup_form,
                    first_seen_document_id
                )
                SELECT :user_id, w.kind, w.lookup_form, w.reading, w.idseq, w.alt_lookup_form,
                       :document_id
                FROM jsonb_to_recordset(CAST(:words AS JSONB))
                    AS w(ord int, kind text, lookup_form text, reading text, idseq int,
                         alt_lookup_form text)
                WHERE NOT EXISTS (
                    SELECT 1 FROM study_cards c
                    WHERE c.user_id = :user_id AND c.kind = w.kind AND c.lookup_form = w.lookup_form
                      AND c.reading IS NOT DISTINCT FROM w.reading
                      AND c.idseq IS NOT DISTINCT FROM w.idseq
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
                            "idseq": w.key.idseq,
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


def token_word(
    conn, document_id: int, token_id: int, piece: int | None = None
) -> CardTokens:
    """The word or grammar term `token_id` is part of, as a card for it is
    keyed — by default, for a predicate group, the word the group is built
    on; with a `piece` of its gloss, the word or grammar term that is, as for
    a token sung in katakana or a group — whether or not it has a gloss to
    study.

    Raises TokenNotFound if the document has no token `token_id`, and
    NotStudyable if the token isn't part of a word, or `piece` doesn't name
    a word or grammar term of its gloss."""
    units = _units(_token_rows(conn, [document_id], token_id))
    if not units:
        raise TokenNotFound()
    unit = units[0]
    if piece is None:
        word = (
            None
            if unit[0].katakana_gloss is not None
            else _unit_word(unit, explicit=True)
        )
    else:
        found = unit_card_tokens(unit, katakana=katakana_lookups(conn, [unit]))
        word = next((w for w in found if w.piece == piece), None)
    if word is None:
        raise NotStudyable()
    return word


def add_card(conn, user_id: int, document_id: int, word: CardTokens):
    """The user's card row for `word`, a word of `document_id`, created if
    they have none, or restored with its history if they removed it.

    Raises NotStudyable unless the word has something to test (see
    _studyable)."""
    key, alt = word.key, word.alt_lookup_form
    if not _studyable(conn, [(key, alt)]):
        raise NotStudyable()
    return conn.execute(
        text(
            f"""
            INSERT INTO study_cards (
                user_id, kind, lookup_form, reading, idseq, alt_lookup_form,
                first_seen_document_id
            )
            VALUES (
                :user_id, :kind, :lookup_form, :reading, :idseq, :alt_lookup_form, :document_id
            )
            ON CONFLICT ON CONSTRAINT study_cards_word_key DO UPDATE SET suspended = FALSE
            RETURNING {CARD_COLUMNS}
            """
        ),
        {
            "user_id": user_id,
            "kind": key.kind,
            "lookup_form": key.lookup_form,
            "reading": key.reading,
            "idseq": key.idseq,
            "alt_lookup_form": alt,
            "document_id": document_id,
        },
    ).one()


def enroll_token(
    conn, user_id: int, document_id: int, token_id: int, piece: int | None = None
):
    """add_card for the word token_word finds for `token_id`. Unlike
    enroll_new_words, this takes a word marked as needing no gloss, read as
    a guess, or sung in katakana, since adding it is an explicit choice."""
    return add_card(
        conn, user_id, document_id, token_word(conn, document_id, token_id, piece)
    )


@dataclass
class TokenWord:
    """A word of a document the user can add to their cards, where it is."""

    # Every token of what it's glossed with, so that any token of a
    # predicate group stands for its head word.
    token_ids: list[int]
    # For a word or grammar term that's one piece of a gloss (a katakana
    # token's or a group's), which one.
    piece: int | None
    key: CardKey
    # How it can be corrected (see CardTokens).
    correction: Literal["reading", "word"] | None
    # The user's card for it (CARD_COLUMNS), removed or not; None if they
    # have none.
    card: object | None


def document_words(conn, user_id: int, document_id: int) -> list[TokenWord]:
    """Every word and grammar term of the document the user could add to
    their cards, as enroll_token takes them, wherever the document has it,
    each with their card for it if they have one."""
    units = document_units(conn, document_id)
    katakana = katakana_lookups(conn, units)
    found = [
        (unit, word)
        for unit in units
        for word in unit_card_tokens(unit, katakana=katakana)
        # Grammar is offered on its piece of the unit's gloss, so not while
        # that gloss is unlinked: with no piece it would pass for the word.
        if word.key.kind != "grammar" or word.piece is not None
    ]
    studyable = _studyable(conn, [(w.key, w.alt_lookup_form) for _, w in found])
    cards = _user_cards(conn, user_id, studyable)
    return [
        TokenWord(
            [row.id for row in unit],
            word.piece,
            word.key,
            word.correction,
            cards.get(word.key),
        )
        for unit, word in found
        if word.key in studyable
    ]
