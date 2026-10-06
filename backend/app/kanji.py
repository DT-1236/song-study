"""What the kanji sidebar on a card's reveal shows about each kanji of its word
or group (docs/flashcards.md, "The kanji sidebar"): KANJIDIC2's readings,
meanings, grade and frequency, the radical it's built from, the reading it has
in the word, and the words of the user's deck it's also in.

Nothing here is stored; it's worked out each time a queue is built.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from unicodedata import normalize

from fsrs import State
from jamdict.kanjidic2 import KangxiRadical
from sqlalchemy import text

from app.glosses import get_jamdict, get_raw_conn
from app.tokenization import furigana_spans_for_reading, is_kanji, to_katakana

# A card is mature once its memory is expected to last this many days,
# Anki's convention.
MATURE_STABILITY_DAYS = 21

# How many of the deck's words a kanji lists, and how many of the other
# components KRADFILE finds in it.
MAX_DECK_WORDS = 5
MAX_COMPONENTS = 3

# KRADFILE decomposes down to bare strokes, which say nothing about a kanji.
_STROKE_SHAPES = frozenset("一｜ノ丶乙マ")

# KANJIDIC2 names a kanji's radical by its standalone form, but the kanji
# contains a variant of it, which is the form KRADFILE finds among its
# components. Each radical's variants, found by comparing the two across
# every kanji.
_RADICAL_VARIANTS: dict[str, tuple[str, ...]] = {
    "艸": ("⺾",),
    "水": ("氵",),
    "人": ("⺅",),
    "手": ("扌",),
    "心": ("忄",),
    "肉": ("月",),
    "玉": ("王",),
    "辵": ("辶",),
    "衣": ("衤",),
    "犬": ("犭",),
    "阜": ("⻖",),
    "邑": ("⻏",),
    "刀": ("刂",),
    "示": ("礻",),
    "火": ("灬",),
    "攴": ("攵",),
    "网": ("罒",),
    "老": ("⺹",),
    "黑": ("黒",),
    "戶": ("戸",),
    "麥": ("麦",),
    "齒": ("歯",),
    "黃": ("黄",),
    "龜": ("亀",),
    "龍": ("竜",),
    "曰": ("日",),
    "匸": ("匚",),
    "襾": ("西",),
    "丿": ("ノ",),
    "八": ("ハ",),
    "彐": ("ヨ",),
    "夊": ("夂",),
    "丨": ("｜",),
    "巛": ("川",),
}


@dataclass(frozen=True)
class KanjiInWord:
    """A kanji as a word is written, with how the word reads it."""

    character: str
    # Its reading there, in hiragana; None where the word's reading doesn't
    # divide among its kanji (今日 as きょう).
    reading: str | None
    # The kana after it in the word, which says which of its kun readings
    # the word is using.
    kana_after: str


@dataclass(frozen=True)
class Radical:
    # The form the kanji contains, which is its classical radical's variant
    # where it has one (氵 for 水).
    character: str
    # The classical radical's English name.
    meaning: str


@dataclass(frozen=True)
class DeckWord:
    """A word the user has a card for."""

    lookup_form: str
    reading: str | None
    status: Literal["new", "learning", "mature"]


@dataclass(frozen=True)
class KanjiEntry:
    character: str
    # All of them, in katakana.
    on_readings: list[str]
    # Only those the word uses, as KANJIDIC2 writes them with the okurigana
    # in brackets (き(こえる)), and how many it has besides.
    kun_readings: list[str]
    more_kun: int
    meanings: list[str]
    grade: int | None
    frequency: int | None
    radical: Radical | None
    # What else KRADFILE finds in it: a visual decomposition that's only a
    # hint, since it goes down to fragments of strokes.
    components: list[str]
    deck_words: list[DeckWord]


@dataclass(frozen=True)
class _Character:
    """What KANJIDIC2 and KRADFILE know of a kanji."""

    on_readings: tuple[str, ...]
    kun_readings: tuple[str, ...]
    meanings: tuple[str, ...]
    grade: int | None
    frequency: int | None
    radical: Radical | None
    components: tuple[str, ...]


# Every kanji looked up so far; None for one KANJIDIC2 has no entry for.
# KANJIDIC2 is finite (about 13,000 characters), so it can't grow without bound.
_characters: dict[str, _Character | None] = {}


def _grouped(conn, sql: str, ids: dict[int, str]) -> dict[str, list]:
    """The rows of `sql`, whose first column is a character's id (and which
    takes the ids' placeholders as `{marks}`), keyed by that character with
    the other columns left of each row."""
    marks = ",".join("?" * len(ids))
    found: dict[str, list] = {}
    for cid, *rest in conn.execute(sql.format(marks=marks), list(ids)):
        found.setdefault(ids[cid], []).append(rest[0] if len(rest) == 1 else rest)
    return found


def load_characters(literals: Iterable[str]) -> None:
    """Reads what the dictionaries know of each of `literals` not yet looked
    up, so that `kanji_entries` finds them without a query apiece."""
    missing = sorted(set(literals) - _characters.keys())
    if not missing:
        return
    conn = get_raw_conn()
    marks = ",".join("?" * len(missing))
    rows = conn.execute(
        f"SELECT ID, literal, grade, freq FROM character WHERE literal IN ({marks})",
        missing,
    ).fetchall()
    ids = {id_: literal for id_, literal, _, _ in rows}
    classical = _grouped(
        conn,
        "SELECT cid, value FROM radical "
        "WHERE rad_type = 'classical' AND cid IN ({marks})",
        ids,
    )
    # rowid order is KANJIDIC2's own order, which the readings and meanings
    # are shown in.
    readings = _grouped(
        conn,
        "SELECT g.cid, r.r_type, r.value FROM reading r "
        "JOIN rm_group g ON g.ID = r.gid "
        "WHERE r.r_type IN ('ja_on', 'ja_kun') AND g.cid IN ({marks}) "
        "ORDER BY g.ID, r.rowid",
        ids,
    )
    meanings = _grouped(
        conn,
        "SELECT g.cid, m.value FROM meaning m "
        "JOIN rm_group g ON g.ID = m.gid "
        # KANJIDIC2 also carries French, Spanish and Portuguese meanings.
        "WHERE m.m_lang = '' AND g.cid IN ({marks}) "
        "ORDER BY g.ID, m.rowid",
        ids,
    )
    entries = {literal: (grade, freq) for _, literal, grade, freq in rows}
    for literal in missing:
        _characters[literal] = (
            _build_character(
                literal,
                *entries[literal],
                classical.get(literal, [None])[0],
                readings.get(literal, []),
                meanings.get(literal, []),
            )
            if literal in entries
            else None
        )


def _build_character(
    literal: str,
    grade: str | None,
    freq: str | None,
    classical_radical: str | None,
    readings: list[list[str]],
    meanings: list[str],
) -> _Character:
    """The `_Character` for `literal` from its KANJIDIC2 columns, its
    classical radical's number, its (type, value) readings and its meanings."""
    # NFC, since KRADFILE writes some components as compatibility characters
    # that look the same but aren't the codepoint a font or a comparison
    # expects (its 辶 is U+FA66).
    components = tuple(normalize("NFC", c) for c in get_jamdict().krad.get(literal, ()))
    radical = None
    if classical_radical is not None:
        kangxi = KangxiRadical.kangxi()[classical_radical]
        shown = _radical_form(kangxi.radical, components)
        radical = Radical(shown, kangxi.meaning)
        # What's left once the radical is accounted for.
        components = tuple(_without_first(components, shown))
    return _Character(
        tuple(v for t, v in readings if t == "ja_on"),
        tuple(v for t, v in readings if t == "ja_kun"),
        tuple(meanings),
        # KANJIDIC2 gives both as text, and omits either for a kanji without it.
        int(grade) if grade else None,
        int(freq) if freq else None,
        radical,
        tuple(c for c in components if c not in _STROKE_SHAPES),
    )


def _character(literal: str) -> _Character | None:
    """What the dictionaries know of `literal`, or None if KANJIDIC2 has no
    entry for it (々)."""
    load_characters([literal])
    return _characters[literal]


def _radical_form(classical: str, components: tuple[str, ...]) -> str:
    """The form of the radical `classical` among a kanji's `components`: its
    own, else a variant of it, else its own anyway."""
    if classical in components:
        return classical
    for variant in _RADICAL_VARIANTS.get(classical, ()):
        if variant in components:
            return variant
    return classical


def _without_first(items: tuple[str, ...], item: str) -> list[str]:
    rest = list(items)
    if item in rest:
        rest.remove(item)
    return rest


def _kana_run(word: str, start: int) -> str:
    """The kana of `word` from `start` up to its next kanji."""
    end = start
    while end < len(word) and not is_kanji(word[end]):
        end += 1
    return word[start:end]


def kanji_in_spans(spans: list[dict], dictionary_form: str) -> list[KanjiInWord]:
    """The kanji of a token, given its furigana `spans` and the dictionary
    form it's an inflection of."""
    surface = "".join(span["text"] for span in spans)
    kanji = []
    for span in spans:
        chars = [ch for ch in span["text"] if is_kanji(ch)]
        # A span of several kanji has one reading between them, which can't
        # be given to any one.
        single = len(span["text"]) == 1 and span["reading"] is not None
        for ch in chars:
            if single and dictionary_form[span["start"] : span["end"]] == ch:
                # The dictionary form's okurigana, which an inflection
                # (聞いた, from 聞く) may have changed.
                after = _kana_run(dictionary_form, span["end"])
            else:
                after = _kana_run(surface, span["end"])
            kanji.append(KanjiInWord(ch, span["reading"] if single else None, after))
    return kanji


def kanji_in_word(word: str, reading: str) -> list[KanjiInWord]:
    """The kanji of `word` read as `reading`, in either script."""
    return kanji_in_spans(furigana_spans_for_reading(word, to_katakana(reading)), word)


def _split_kun(kun: str) -> tuple[str, str]:
    """A KANJIDIC2 kun reading as its stem and okurigana: `き.こえる` is き and
    こえる, `-どお.り` is どお and り, and `かん-` is かん."""
    stem, _, okurigana = kun.strip("-").partition(".")
    return stem, okurigana


def _kun_in_play(
    kun_readings: Iterable[str], reading: str | None, kana_after: str
) -> list[str]:
    """The kun readings of a kanji that its `reading` in a word is, given the
    kana `kana_after` it; none where the word reads it by on'yomi."""
    if reading is None:
        return []
    split = [(kun, *_split_kun(kun)) for kun in kun_readings]
    # A voiced reading is first tried as it is, then as the unvoiced one it
    # is the rendaku of (女神's 神 is がみ, KANJIDIC2's かみ). Decomposing the
    # first kana drops its voicing mark, voiced or half-voiced.
    unvoiced = normalize("NFD", reading[:1])[0] + reading[1:]
    for candidate in dict.fromkeys((reading, unvoiced)):
        matches = [
            (kun, okurigana) for kun, stem, okurigana in split if stem == candidate
        ]
        if matches:
            # Of several, the one whose okurigana the word has (聞こえる is
            # き.こえる, not き.く); if the dictionary form didn't give it,
            # all of them.
            fitting = [
                kun for kun, okurigana in matches if kana_after.startswith(okurigana)
            ]
            return fitting or [kun for kun, _ in matches]
    return []


def _display_kun(kun: str) -> str:
    head, dot, okurigana = kun.partition(".")
    return f"{head}({okurigana})" if dot else head


def deck_cards(
    conn, user_id: int, characters: Iterable[str]
) -> dict[str, list[tuple[int, DeckWord]]]:
    """The user's word cards, not removed from study, whose word has each of
    `characters`, shortest word first."""
    characters = sorted(set(characters))
    if not characters:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT k.character, c.id, c.lookup_form, c.reading,
                   CASE
                       WHEN c.last_review IS NULL THEN 'new'
                       WHEN c.state = :review AND c.stability >= :mature THEN 'mature'
                       ELSE 'learning'
                   END AS status
            FROM unnest(CAST(:characters AS TEXT[])) AS k(character)
            JOIN study_cards c ON strpos(c.lookup_form, k.character) > 0
            WHERE c.user_id = :user_id AND c.kind = 'recognition' AND NOT c.suspended
            ORDER BY k.character, length(c.lookup_form), c.lookup_form, c.reading
            """
        ),
        {
            "user_id": user_id,
            "characters": characters,
            "review": int(State.Review),
            "mature": MATURE_STABILITY_DAYS,
        },
    )
    found: dict[str, list[tuple[int, DeckWord]]] = {}
    for row in rows:
        found.setdefault(row.character, []).append(
            (row.id, DeckWord(row.lookup_form, row.reading, row.status))
        )
    return found


def kanji_entries(
    kanji: Iterable[KanjiInWord],
    deck: dict[str, list[tuple[int, DeckWord]]],
    card_id: int,
) -> list[KanjiEntry]:
    """A sidebar entry for each distinct kanji of `kanji`, in order, with the
    words of `deck` (see deck_cards) other than the card `card_id`'s own."""
    written: dict[str, list[KanjiInWord]] = {}
    for item in kanji:
        written.setdefault(item.character, []).append(item)
    entries = []
    for literal, occurrences in written.items():
        known = _character(literal)
        if known is None:
            continue
        # A kanji the word reads two ways (一人一人) lists both.
        in_play = list(
            dict.fromkeys(
                kun
                for item in occurrences
                for kun in _kun_in_play(
                    known.kun_readings, item.reading, item.kana_after
                )
            )
        )
        deck_words = [word for id_, word in deck.get(literal, []) if id_ != card_id]
        entries.append(
            KanjiEntry(
                character=literal,
                on_readings=list(known.on_readings),
                kun_readings=[_display_kun(kun) for kun in in_play],
                more_kun=len(known.kun_readings) - len(in_play),
                meanings=list(known.meanings),
                grade=known.grade,
                frequency=known.frequency,
                radical=known.radical,
                components=list(known.components[:MAX_COMPONENTS]),
                deck_words=deck_words[:MAX_DECK_WORDS],
            )
        )
    return entries
