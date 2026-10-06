"""What a queued study card shows: the line of a song it plays, and the
options it's answered from (docs/flashcards.md, "The card types" and "Which
line plays").

Neither is stored. A card's line is chosen each time a queue is built, from
the songs its word is in now, so lyrics changing underneath a card can't
leave it pointing at a line that's gone. Its options are drawn afresh each
time too, so a card can't be learned by where its answer sits.
"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from functools import cached_property

from sqlalchemy import text

from app.cards import (
    CardKey,
    CardTokens,
    katakana_lookups,
    unit_card_tokens,
    units_by_document,
)
from app.db import DOCUMENT_COLUMNS
from app.glosses import GlossKey, gloss_entries, rank_senses
from app.grammar import grammar_category, grammar_notes, notes_overlap
from app.kanji import (
    CardKanji,
    KanjiEntry,
    KanjiInWord,
    card_kanji,
    deck_cards,
    kanji_entries,
    kanji_in_spans,
    kanji_in_word,
    load_characters,
)

OPTION_COUNT = 4

# How many senses each option of a word's card shows, the same on every
# option: a hedge against not knowing which sense a line means, kept short
# enough for four options to fit on a phone. The reveal shows the rest.
OPTION_SENSE_LIMIT = 2

# A wrong option mustn't share a meaning with any of this many of the word's
# senses: as many as the reading view shows before "Show more", the ones the
# word is most likely known by.
_KNOWN_SENSE_LIMIT = 5

# How many of the user's other words a card draws its wrong options from
# when its own song runs short, per part of speech.
_DECK_SAMPLE_SIZE = 30


@dataclass(frozen=True)
class Audio:
    youtube_video_id: str
    # When the line is sung, in seconds into the video.
    start: float
    end: float


@dataclass(frozen=True)
class Line:
    """The line of a song a card plays."""

    document_id: int
    title: str
    # Which of the song's lines, as its text splits on line breaks: the
    # index of its timing.
    index: int
    text: str
    # The token the card is about, the first of an accepted phrase's: the
    # one to correct the reading of.
    token_id: int
    # Where in `text` the word or grammar term the card asks about is, and
    # the group it's part of — a predicate group, or a phrase with the
    # grammar attached to it — as [begin, end) offsets. A word on its own is
    # its own group.
    focus: tuple[int, int]
    group: tuple[int, int]
    # None when the line can't be played: the song has no video, or no
    # timing for this line.
    audio: Audio | None
    # For a word or grammar term sung in katakana, its dictionary form as its
    # gloss writes it (声 for コエ); None for one that isn't.
    written_as: str | None


@dataclass(frozen=True)
class Option:
    # A word's option: the senses it shows, each as its glosses.
    senses: list[list[str]] | None = None
    # A grammar term's option: what it says the term does.
    note: str | None = None


@dataclass
class Content:
    """What a card shows besides its own row."""

    # None for a card whose word or grammar term is in none of the user's
    # songs any more.
    line: Line | None
    options: list[Option]
    # The index of the right option; None, with no options, for a word that
    # no longer has a dictionary entry to ask about.
    answer: int | None
    # For a word: every sense it has, ranked for how the line uses it. Its
    # option shows the first OPTION_SENSE_LIMIT.
    senses: list[dict] = field(default_factory=list)
    # For the reveal: each kanji of the word, or the group it's in, as it's
    # used there.
    kanji: list[CardKanji] = field(default_factory=list)


@dataclass
class Queue:
    # Each card's row with its content.
    cards: list[tuple[object, Content]]
    # The sidebar entry of every kanji of the cards, by character: sent once
    # however many cards have it.
    kanji: dict[str, KanjiEntry]


@dataclass
class Song:
    id: int
    title: str
    text: str
    youtube_video_id: str | None
    # Each line's {"start", "end"}, or None for an untimed line; None for a
    # song with no timings at all.
    timings: list[dict | None] | None
    # Its tokens, grouped into what's glossed together (see cards._units).
    units: list[list]


def load_songs(
    conn, user_id: int, document_ids: list[int] | None = None
) -> dict[int, Song]:
    """The user's songs with their tokens, by id: those in `document_ids`,
    or all of them."""
    only = "" if document_ids is None else "AND id = ANY(:document_ids)"
    rows = conn.execute(
        text(
            f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE owner_id = :user_id {only}"
        ),
        {"user_id": user_id, "document_ids": document_ids},
    ).all()
    units = units_by_document(conn, [row.id for row in rows])
    return {
        row.id: Song(
            row.id,
            row.title,
            row.text,
            row.youtube_video_id,
            # Edited timings take the place of LRCLIB's, as on the song's
            # page.
            row.edited_lines if row.edited_lines is not None else row.lrclib_lines,
            units.get(row.id, []),
        )
        for row in rows
    }


def line_index(text: str, offset: int) -> int:
    """The index of the line of `text` the character at `offset` is on,
    among the lines text.split("\\n") gives."""
    return text.count("\n", 0, offset)


@dataclass
class _Occurrence:
    """Somewhere a song has a card's word or grammar term."""

    song: Song
    # The unit (see cards._units) it's part of.
    unit: list
    found: CardTokens

    @cached_property
    def line(self) -> Line:
        lyrics = self.song.text
        begin = self.found.tokens[0].char_begin
        start = lyrics.rfind("\n", 0, begin) + 1
        stop = lyrics.find("\n", begin)
        if stop == -1:
            stop = len(lyrics)

        def on_line(first, last) -> tuple[int, int]:
            # A span is clipped to the line, though no group crosses one.
            return (
                max(first.char_begin, start) - start,
                min(last.char_end, stop) - start,
            )

        focus = on_line(self.found.tokens[0], self.found.tokens[-1])
        if self.found.span is not None:
            # A katakana word's span is within its one token.
            focus = (focus[0] + self.found.span[0], focus[0] + self.found.span[1])

        index = line_index(lyrics, begin)
        return Line(
            self.song.id,
            self.song.title,
            index,
            lyrics[start:stop],
            self.found.tokens[0].id,
            focus,
            on_line(self.unit[0], self.unit[-1]),
            _audio(self.song, index),
            self.found.written_as,
        )


def _audio(song: Song, index: int) -> Audio | None:
    """How to play line `index` of `song`, or None if it can't be."""
    timings = song.timings or []
    timing = timings[index] if index < len(timings) else None
    if song.youtube_video_id is None or timing is None:
        return None
    # A line starting where the next does (two lines sung at once in an LRC
    # file) has no length to play.
    if timing["end"] <= timing["start"]:
        return None
    return Audio(song.youtube_video_id, timing["start"], timing["end"])


def _occurrences(conn, songs: Iterable[Song]) -> dict[CardKey, list[_Occurrence]]:
    """Everywhere `songs` have each word and grammar term a card can be for,
    by key."""
    songs = list(songs)
    katakana = katakana_lookups(conn, (unit for song in songs for unit in song.units))
    found: dict[CardKey, list[_Occurrence]] = {}
    for song in songs:
        for unit in song.units:
            for card_tokens in unit_card_tokens(unit, katakana=katakana):
                found.setdefault(card_tokens.key, []).append(
                    _Occurrence(song, unit, card_tokens)
                )
    return found


def _choose_occurrence(
    occurrences: list[_Occurrence], studied: int | None, rng: random.Random
) -> _Occurrence | None:
    """The occurrence of a card's word to play: one in the song `studied`,
    if it has any, and one whose line can be played over one whose can't.
    Otherwise it's left to chance, so a card plays different lines over
    time."""
    in_studied = [o for o in occurrences if o.song.id == studied]
    candidates = in_studied or occurrences
    playable = [o for o in candidates if o.line.audio is not None]
    return rng.choice(playable or candidates) if candidates else None


# The near-synonym guard: two words share a meaning when a gloss of one is a
# gloss of the other, or when their glosses share a word that carries
# meaning. Deliberately cheap and eager to match — a wrong option turned away
# costs only another draw, while one let through can be a second right
# answer.

# Words that only hold a gloss together. Light verbs (do, get, have,
# become) aren't among them, though "to get angry" and "to get tired" then
# count as alike: they're what する, なる and ある mean.
# A list literal would be formatted one word to a line, eighty lines of it.
_STOPWORDS = frozenset(
    """
    a an the to be is are am was were been being of or and nor in on at by
    for with without from as into onto upon up down out off over under about
    than then that this these those it its one ones oneself someone somebody
    something somewhere etc can could will would may might must shall should
    very much more most so such some any all
    """.split()  # noqa: SIM905
)
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")
_WORD_RE = re.compile(r"[a-z]+")
_ENDINGS = ("ing", "ed", "es", "s", "ly")


def _word_forms(word: str) -> set[str]:
    """`word`, and what it'd be without each common ending it has, so that
    "hears", "hearing" and "hear" meet. Every candidate rather than one guess
    at the stem, since "loves" is love + s but "kisses" is kiss + es."""
    forms = {word}
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            forms.add(word[: -len(ending)])
    return forms


@dataclass(frozen=True)
class _Meaning:
    glosses: frozenset[str]
    words: frozenset[str]

    def overlaps(self, other: _Meaning) -> bool:
        return bool(self.glosses & other.glosses or self.words & other.words)


def _meaning(senses: list[dict]) -> _Meaning:
    """The glosses of `senses` and the words in them that carry meaning, as
    two words' meanings are compared."""
    glosses: set[str] = set()
    words: set[str] = set()
    for sense in senses:
        for gloss in sense["gloss"]:
            # A parenthetical narrows where a gloss applies ("(of a
            # person)") rather than saying what it means.
            plain = " ".join(_PARENTHETICAL_RE.sub(" ", gloss.lower()).split())
            if plain:
                glosses.add(plain)
            for word in _WORD_RE.findall(plain):
                if len(word) > 1 and word not in _STOPWORDS:
                    words |= _word_forms(word)
    return _Meaning(frozenset(glosses), frozenset(words))


@dataclass
class WordSenses:
    """A word as an option shows it."""

    lookup_form: str
    # What a wrong option for it should match: its part of speech, or
    # "phrase"; None when that isn't known.
    pos_class: str | None
    # Its senses, ranked, each with English glosses.
    senses: list[dict]


def pick_wrong_options(
    target: WordSenses,
    candidates: Iterable[WordSenses],
    count: int = OPTION_COUNT - 1,
) -> list[WordSenses]:
    """Up to `count` of `candidates`, which come best first, to show as
    wrong options for `target`. None shares a meaning or a dictionary entry
    with it, or a meaning with another. A candidate of the target's part of
    speech with at least as many senses as its option shows is taken as
    soon as it's reached; failing enough of those, one with fewer senses,
    then one of another part of speech, since each is a tell: an option
    answerable by its shape, or by being shorter than the rest."""
    shown = min(OPTION_SENSE_LIMIT, len(target.senses))
    known = _meaning(target.senses[:_KNOWN_SENSE_LIMIT])
    target_entries = {sense["entry_idseq"] for sense in target.senses}
    picked: list[tuple[WordSenses, _Meaning]] = []
    spare: list[tuple[WordSenses, _Meaning]] = []

    def fits(meaning: _Meaning) -> bool:
        return not any(meaning.overlaps(other) for _, other in picked)

    for candidate in candidates:
        # The same spelling read another way (辛い, からい and つらい) is
        # another word, but one a learner may know the target as.
        if not candidate.senses or candidate.lookup_form == target.lookup_form:
            continue
        if target_entries & {sense["entry_idseq"] for sense in candidate.senses}:
            continue
        meaning = _meaning(candidate.senses[:shown])
        if meaning.overlaps(known):
            continue
        if candidate.pos_class == target.pos_class and len(candidate.senses) >= shown:
            if fits(meaning):
                picked.append((candidate, meaning))
                if len(picked) == count:
                    return [c for c, _ in picked]
        else:
            spare.append((candidate, meaning))

    # Stable, so each tier keeps the order the candidates came in.
    spare.sort(
        key=lambda pair: (
            pair[0].pos_class != target.pos_class,
            len(pair[0].senses) < shown,
        )
    )
    for candidate, meaning in spare:
        if len(picked) == count:
            break
        if fits(meaning):
            picked.append((candidate, meaning))
    return [c for c, _ in picked]


def word_content(
    target: WordSenses,
    candidates: Iterable[WordSenses],
    line: Line | None,
    rng: random.Random,
) -> Content:
    """A word card's content: `target`'s option among wrong ones drawn from
    `candidates` (see pick_wrong_options), in random order."""
    if not target.senses:
        return Content(line, [], None)
    shown = min(OPTION_SENSE_LIMIT, len(target.senses))
    words = [target, *pick_wrong_options(target, candidates)]
    rng.shuffle(words)
    return Content(
        line,
        [
            Option(senses=[sense["gloss"] for sense in word.senses[:shown]])
            for word in words
        ],
        words.index(target),
        target.senses,
    )


def grammar_content(term: str, line: Line | None, rng: random.Random) -> Content:
    """A grammar card's content: `term`'s note among the notes of other
    grammar, those of its own kind first, in random order. No two notes
    describe their grammar alike enough to be taken for each other."""
    notes = grammar_notes()
    category = grammar_category(term)
    others = [other for other in notes if other != term]
    rng.shuffle(others)
    # Stable, so each kind stays shuffled.
    others.sort(key=lambda other: grammar_category(other) != category)
    picked = [term]
    for other in others:
        if len(picked) == OPTION_COUNT:
            break
        if not any(notes_overlap(other, p) for p in picked):
            picked.append(other)
    rng.shuffle(picked)
    return Content(line, [Option(note=notes[t]) for t in picked], picked.index(term))


@dataclass(frozen=True)
class _Word:
    """A word, with what drawing wrong options for or from it needs."""

    key: CardKey
    alt_lookup_form: str | None
    # The part of speech its senses are ranked for: its first token's.
    pos_major: str
    # See WordSenses.pos_class.
    pos_class: str | None

    @classmethod
    def of(cls, found: CardTokens) -> _Word:
        head = found.tokens[0]
        # A katakana word's is its gloss's, since the katakana token's own tag
        # is Sudachi's guess at an unknown word.
        pos_major = found.pos_major or head.part_of_speech[0]
        # An accepted phrase's senses are an idiom's, whatever its first
        # token is.
        phrase = head.accepted_phrase is not None
        return cls(
            found.key,
            found.alt_lookup_form,
            pos_major,
            "phrase" if phrase else pos_major,
        )

    @property
    def gloss_key(self) -> GlossKey:
        return (self.key.lookup_form, self.key.reading)


class _Glosses:
    """Words' glosses, looked up as needed and kept for the rest of the
    queue."""

    def __init__(self, conn):
        self._conn = conn
        self._found: dict[GlossKey, tuple[object, str]] = {}
        # Ranked once per word, though a word is drawn for many cards.
        self._senses: dict[_Word, WordSenses] = {}

    def fetch(self, words: Iterable[_Word]) -> None:
        """Look up the glosses of `words` not looked up yet, in one go."""
        missing = {
            w.gloss_key: w.alt_lookup_form
            for w in words
            if w.gloss_key not in self._found
        }
        if missing:
            self._found |= gloss_entries(self._conn, missing.items())

    def senses(self, word: _Word) -> WordSenses:
        """`word` as an option shows it, once fetched: no senses unless it's
        glossed from a JMDict headword."""
        if word not in self._senses:
            entries, source = self._found.get(word.gloss_key, (None, None))
            senses = []
            if source == "jmdict":
                senses = [
                    sense
                    for sense in rank_senses(entries, word.pos_major)
                    if sense["gloss"]
                ]
            self._senses[word] = WordSenses(
                word.key.lookup_form, word.pos_class, senses
            )
        return self._senses[word]


class _Library:
    """Where a queue's wrong options come from: the words of a card's own
    song, then the user's other words, loaded only once a card needs
    them."""

    def __init__(
        self,
        conn,
        user_id: int,
        occurrences: dict[CardKey, list[_Occurrence]] | None = None,
    ):
        """`occurrences` in every one of the user's songs, if already
        found."""
        self._conn, self._user_id = conn, user_id
        self._occurrences = occurrences
        self._song_words: dict[int, list[_Word]] = {}
        self._deck: list[_Word] | None = None

    def song_words(self, song: Song) -> list[_Word]:
        """The words `song` would give cards (see cards.harvest), less those
        without a JMDict headword, each once."""
        if song.id not in self._song_words:
            words: dict[CardKey, _Word] = {}
            for unit in song.units:
                for found in unit_card_tokens(unit, explicit=False):
                    if found.key.kind == "recognition":
                        words.setdefault(found.key, _Word.of(found))
            self._song_words[song.id] = list(words.values())
        return self._song_words[song.id]

    def deck(self) -> list[_Word]:
        """The words the user has a card for that are in a song of theirs."""
        if self._deck is None:
            card_keys = {
                CardKey(*row)
                for row in self._conn.execute(
                    text(
                        """
                        SELECT kind, lookup_form, reading FROM study_cards
                        WHERE user_id = :user_id AND kind = 'recognition'
                        """
                    ),
                    {"user_id": self._user_id},
                )
            }
            if self._occurrences is None:
                songs = load_songs(self._conn, self._user_id)
                self._occurrences = _occurrences(self._conn, songs.values())
            self._deck = [
                _Word.of(occurrences[0].found)
                for key, occurrences in self._occurrences.items()
                if key in card_keys
            ]
        return self._deck

    def candidates(
        self, target: _Word, song: Song | None, glosses: _Glosses, rng: random.Random
    ) -> Iterator[WordSenses]:
        """Words to draw `target`'s wrong options from, best first: those of
        its part of speech from `song`, the line's, then from the user's
        other words; then the same of any other part of speech. Each batch
        is fetched only once the one before it is used up."""

        # Left out here as well as by pick_wrong_options, so they're neither
        # looked up nor take a place in a deck sample.
        def other_spelling(word: _Word) -> bool:
            return word.key.lookup_form != target.key.lookup_form

        def same(word: _Word) -> bool:
            return word.pos_class == target.pos_class

        own = [w for w in (self.song_words(song) if song else []) if other_spelling(w)]
        rng.shuffle(own)
        own_keys = {w.key for w in own}

        def deck() -> list[_Word]:
            words = [
                w for w in self.deck() if w.key not in own_keys and other_spelling(w)
            ]
            rng.shuffle(words)
            return words

        def batches() -> Iterator[list[_Word]]:
            # The song's own words first: familiar ones make weaker
            # giveaways than strangers.
            yield [w for w in own if same(w)]
            # Another part of speech is a tell, so the rest of the deck comes
            # first.
            others = deck()
            yield [w for w in others if same(w)][:_DECK_SAMPLE_SIZE]
            yield [w for w in own if not same(w)]
            yield [w for w in others if not same(w)][:_DECK_SAMPLE_SIZE]

        for batch in batches():
            glosses.fetch(batch)
            for word in batch:
                yield glosses.senses(word)


def _writes_its_kanji(occurrence: _Occurrence | None) -> bool:
    """Whether the line of `occurrence` writes the kanji of its word: not for
    a word sung in katakana, nor one with no line at all."""
    return occurrence is not None and occurrence.found.written_as is None


def _furigana(conn, occurrences: Iterable[_Occurrence | None]) -> dict[int, list]:
    """The furigana, as the page shows it, of each token in the groups of the
    occurrences that write their kanji, by token id."""
    token_ids = [
        row.id
        for occurrence in occurrences
        if _writes_its_kanji(occurrence)
        for row in occurrence.unit
    ]
    rows = conn.execute(
        text(
            """
            SELECT id, COALESCE(furigana_override, furigana_spans) AS spans
            FROM tokens WHERE id = ANY(:token_ids)
            """
        ),
        {"token_ids": token_ids},
    )
    return {row.id: row.spans for row in rows}


def _written_kanji(
    key: CardKey, occurrence: _Occurrence | None, furigana: dict[int, list]
) -> list[KanjiInWord]:
    """The kanji of the group a card's word or grammar term is in on its line,
    given the `furigana` of the line's tokens; those of the word on its own
    when the line doesn't write them (see _writes_its_kanji)."""
    if _writes_its_kanji(occurrence):
        return [
            kanji
            for row in occurrence.unit
            for kanji in kanji_in_spans(furigana[row.id], row.dictionary_form)
        ]
    return kanji_in_word(key.lookup_form, key.reading) if key.reading else []


def queue_contents(
    conn,
    user_id: int,
    cards: list,
    songs: dict[int, Song],
    studied: int | None,
    rng: random.Random | None = None,
) -> Queue:
    """Each of the user's `cards` (rows with their kind, key and alternate
    spelling) with its content, its line from `songs`: the song `studied`'s,
    if it has the card's word, else any of them, all the user's songs; and
    the sidebar entries of their kanji. `rng` draws the lines and options."""
    rng = rng or random.Random()
    occurrences = _occurrences(conn, songs.values())
    library = _Library(conn, user_id, occurrences if studied is None else None)
    glosses = _Glosses(conn)

    keys = [CardKey(card.kind, card.lookup_form, card.reading) for card in cards]
    chosen = [
        _choose_occurrence(occurrences.get(key, []), studied, rng) for key in keys
    ]
    targets = {
        key: (
            # Looked up under the card's own alternate spelling, as it was
            # enrolled.
            replace(_Word.of(occurrence.found), alt_lookup_form=card.alt_lookup_form)
            if occurrence
            # In no song, so nothing says how it's used: its senses keep
            # JMDict's order.
            else _Word(key, card.alt_lookup_form, "", None)
        )
        for card, key, occurrence in zip(cards, keys, chosen, strict=True)
        if key.kind == "recognition"
    }
    # Every word card's own gloss, in one lookup.
    glosses.fetch(targets.values())

    furigana = _furigana(conn, chosen)
    written = [
        _written_kanji(key, occurrence, furigana)
        for key, occurrence in zip(keys, chosen, strict=True)
    ]
    characters = {item.character for kanji in written for item in kanji}
    # Every card's kanji, in one lookup each from KANJIDIC2 and the deck.
    load_characters(characters)
    entries = kanji_entries(characters, deck_cards(conn, user_id, characters))

    cards_content = []
    for card, key, occurrence, kanji in zip(cards, keys, chosen, written, strict=True):
        line = occurrence.line if occurrence else None
        if key.kind == "grammar":
            content = grammar_content(key.lookup_form, line, rng)
        else:
            target = targets[key]
            song = occurrence.song if occurrence else None
            content = word_content(
                glosses.senses(target),
                library.candidates(target, song, glosses, rng),
                line,
                rng,
            )
        content.kanji = card_kanji(kanji, entries)
        cards_content.append((card, content))
    return Queue(cards_content, entries)


@dataclass(frozen=True)
class WeakWord:
    """A word or grammar term of a song the user's card for is fading."""

    card_id: int
    lookup_form: str
    reading: str | None
    # Their chance of recalling it now, 0 to 1.
    retrievability: float
    # Where in its line it is, as [begin, end) offsets.
    focus: tuple[int, int]
    # What it means: a word's first senses, as its options show them, or a
    # grammar term's note. None for a word with no dictionary entry any more.
    meaning: Option | None


@dataclass(frozen=True)
class RunLine:
    """A line of a song, for playing it through."""

    index: int
    text: str
    audio: Audio | None
    weak: list[WeakWord]


def run_through_lines(
    conn, song: Song, weak: dict[CardKey, tuple[int, float]]
) -> list[RunLine]:
    """Each of `song`'s lines, with the words and grammar terms in `weak` (by
    key, to the card's id and retrievability) that it has, the weakest
    first."""
    occurrences = _occurrences(conn, [song])
    present = {key: occurrences[key] for key in weak if key in occurrences}
    words = {
        key: _Word.of(os[0].found)
        for key, os in present.items()
        if key.kind == "recognition"
    }
    glosses = _Glosses(conn)
    glosses.fetch(words.values())
    notes = grammar_notes()

    def meaning(key: CardKey) -> Option | None:
        if key.kind == "grammar":
            return Option(note=notes[key.lookup_form])
        senses = glosses.senses(words[key]).senses
        if not senses:
            return None
        return Option(senses=[s["gloss"] for s in senses[:OPTION_SENSE_LIMIT]])

    by_line: dict[int, list[WeakWord]] = {}
    for key, found in present.items():
        card_id, retrievability = weak[key]
        for occurrence in found:
            line = occurrence.line
            by_line.setdefault(line.index, []).append(
                WeakWord(
                    card_id,
                    key.lookup_form,
                    key.reading,
                    retrievability,
                    line.focus,
                    meaning(key),
                )
            )
    return [
        RunLine(
            index,
            text,
            _audio(song, index),
            sorted(by_line.get(index, []), key=lambda w: w.retrievability),
        )
        for index, text in enumerate(song.text.split("\n"))
    ]
