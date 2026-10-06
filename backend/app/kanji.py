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

from jamdict.kanjidic2 import KangxiRadical
from sqlalchemy import text

from app.cards import is_mature
from app.glosses import KanjidicRow, get_jamdict, kanjidic_rows
from app.tokenization import furigana_spans_for_reading, is_kanji, to_katakana

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

    # So that the sidebar can leave out the card it's shown on.
    card_id: int
    lookup_form: str
    reading: str | None
    status: Literal["new", "learning", "mature"]


@dataclass(frozen=True)
class CardKanji:
    """A kanji as a card's word or group uses it."""

    character: str
    # Only the kun readings the word uses, as KANJIDIC2 writes them with the
    # okurigana in brackets (き(こえる)), and how many it has besides.
    kun_readings: list[str]
    more_kun: int


@dataclass(frozen=True)
class KanjiEntry:
    """What the sidebar shows of a kanji whichever card it's on."""

    # All of them, in katakana.
    on_readings: list[str]
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


def load_characters(literals: Iterable[str]) -> None:
    """Reads what the dictionaries know of each of `literals` not yet looked
    up, so that `card_kanji` and `kanji_entries` find them without a query apiece."""
    missing = sorted(set(literals) - _characters.keys())
    rows = kanjidic_rows(missing)
    for literal in missing:
        _characters[literal] = (
            _build_character(literal, rows[literal]) if literal in rows else None
        )


def _build_character(literal: str, row: KanjidicRow) -> _Character:
    """The `_Character` for `literal` from its KANJIDIC2 `row`."""
    # NFC, since KRADFILE writes some components as compatibility characters
    # that look the same but aren't the codepoint a font or a comparison
    # expects (its 辶 is U+FA66).
    components = tuple(normalize("NFC", c) for c in get_jamdict().krad.get(literal, ()))
    radical = None
    if row.classical_radical is not None:
        kangxi = KangxiRadical.kangxi()[row.classical_radical]
        shown = _radical_form(kangxi.radical, components)
        radical = Radical(shown, kangxi.meaning)
        # What's left once the radical is accounted for.
        components = tuple(_without_first(components, shown))
    return _Character(
        tuple(v for t, v in row.readings if t == "ja_on"),
        tuple(v for t, v in row.readings if t == "ja_kun"),
        tuple(row.meanings),
        # KANJIDIC2 gives both as text, and omits either for a kanji without it.
        int(row.grade) if row.grade else None,
        int(row.freq) if row.freq else None,
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
) -> dict[str, list[DeckWord]]:
    """The user's word cards, not removed from study, whose word has each of
    `characters`, shortest word first: as many as a sidebar shows, and one
    more."""
    characters = sorted(set(characters))
    if not characters:
        return {}
    rows = conn.execute(
        text(
            """
            WITH ranked AS (
                SELECT k.character, c.id, c.lookup_form, c.reading,
                       c.last_review, c.state, c.stability,
                       row_number() OVER (PARTITION BY k.character ORDER BY length(c.lookup_form), c.lookup_form, c.reading) AS rn
                FROM unnest(CAST(:characters AS TEXT[])) AS k(character)
                JOIN study_cards c ON strpos(c.lookup_form, k.character) > 0
                WHERE c.user_id = :user_id AND c.kind = 'recognition' AND NOT c.suspended
            )
            SELECT character, id, lookup_form, reading, last_review, state, stability
            FROM ranked
            WHERE rn <= :max_rows
            ORDER BY character, rn
            """
        ),
        {
            "user_id": user_id,
            "characters": characters,
            "max_rows": MAX_DECK_WORDS + 1,
        },
    )
    found: dict[str, list[DeckWord]] = {}
    for row in rows:
        if row.last_review is None:
            status = "new"
        elif is_mature(row.state, row.stability):
            status = "mature"
        else:
            status = "learning"
        found.setdefault(row.character, []).append(
            DeckWord(row.id, row.lookup_form, row.reading, status)
        )
    return found


def card_kanji(
    kanji: Iterable[KanjiInWord], entries: dict[str, KanjiEntry]
) -> list[CardKanji]:
    """Each distinct kanji of `kanji` that has one of `entries` (see
    kanji_entries), in order, with the kun readings the word uses of it."""
    written: dict[str, list[KanjiInWord]] = {}
    for item in kanji:
        written.setdefault(item.character, []).append(item)
    used = []
    for literal, occurrences in written.items():
        # Only those with an entry, so that the sidebar finds one for each.
        if literal not in entries:
            continue
        known = _characters[literal]
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
        used.append(
            CardKanji(
                character=literal,
                kun_readings=[_display_kun(kun) for kun in in_play],
                more_kun=len(known.kun_readings) - len(in_play),
            )
        )
    return used


def kanji_entries(
    characters: Iterable[str], deck: dict[str, list[DeckWord]]
) -> dict[str, KanjiEntry]:
    """The sidebar entry of each of `characters` that KANJIDIC2 has, by
    character, with its words of `deck` (see deck_cards)."""
    entries = {}
    for literal in characters:
        known = _character(literal)
        if known is None:
            continue
        entries[literal] = KanjiEntry(
            on_readings=list(known.on_readings),
            meanings=list(known.meanings),
            grade=known.grade,
            frequency=known.frequency,
            radical=known.radical,
            components=list(known.components[:MAX_COMPONENTS]),
            deck_words=deck.get(literal, []),
        )
    return entries
