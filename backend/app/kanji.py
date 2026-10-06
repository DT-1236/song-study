"""What the kanji sidebar on a card's reveal shows about each kanji of its word
or group (docs/flashcards.md, "The kanji sidebar"): KANJIDIC2's readings,
meanings, grade and frequency, the radical it's built from, the reading it has
in the word, and the words of the user's deck it's also in.

Nothing here is stored; it's worked out each time a queue is built.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal
from unicodedata import normalize

from fsrs import State
from sqlalchemy import text

from app.glosses import get_jamdict
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


@lru_cache(maxsize=4096)
def _character(literal: str) -> _Character | None:
    """What the dictionaries know of `literal`, or None if KANJIDIC2 has no
    entry for it (々)."""
    jam = get_jamdict()
    found = jam.kd2.get_char(literal)
    if found is None:
        return None
    groups = found.rm_groups
    # NFC, since KRADFILE writes some components as compatibility characters
    # that look the same but aren't the codepoint a font or a comparison
    # expects (its 辶 is U+FA66).
    components = tuple(normalize("NFC", c) for c in jam.krad.get(literal, ()))
    radical = None
    if found.radical is not None:
        classical = found.radical.radical
        shown = _radical_form(classical, components)
        radical = Radical(shown, found.radical.meaning)
        # What's left once the radical is accounted for.
        components = tuple(_without_first(components, shown))
    components = tuple(c for c in components if c not in _STROKE_SHAPES)
    return _Character(
        tuple(r.value for group in groups for r in group.on_readings),
        tuple(r.value for group in groups for r in group.kun_readings),
        # KANJIDIC2 also carries French, Spanish and Portuguese meanings.
        tuple(m.value for group in groups for m in group.meanings if m.m_lang == ""),
        # KANJIDIC2 gives both as text, and omits either for a kanji without it.
        int(found.grade) if found.grade else None,
        int(found.freq) if found.freq else None,
        radical,
        components,
    )


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
