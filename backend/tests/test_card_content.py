"""What a queued card shows: the line it plays, and the options it's answered
from."""

from __future__ import annotations

import itertools
import json
import random

import pytest
from sqlalchemy import text

from app.card_content import (
    OPTION_COUNT,
    WordSenses,
    grammar_content,
    line_index,
    pick_wrong_options,
    word_content,
)
from app.grammar import (
    _OVERLAPPING_NOTES,
    grammar_category,
    grammar_notes,
    notes_overlap,
)
from app.main import (
    DocumentCreate,
    LineTimingsUpdate,
    PhraseAcceptance,
)
from tests.support import (
    accept_phrase_suggestions_endpoint,
    create_document,
    create_tokenized_document,
    document_tokens,
    empty_gloss_cache,
    get_all_songs_queue,
    get_document_tokens,
    save_line_timings,
    start_song_session,
)

_entry_ids = itertools.count(1)


def _word(lookup_form: str, *senses: list[str], pos: str | None = "動詞") -> WordSenses:
    """A word with `senses`, each a list of glosses, from an entry of its
    own."""
    entry = next(_entry_ids)
    return WordSenses(
        lookup_form,
        pos,
        [
            {"pos": [], "misc": [], "field": [], "gloss": glosses, "entry_idseq": entry}
            for glosses in senses
        ],
    )


def _forms(words: list[WordSenses]) -> list[str]:
    return [w.lookup_form for w in words]


CALL = _word("呼ぶ", ["to call out (to)", "to call"], ["to summon (a doctor, etc.)"])
SING = _word("歌う", ["to sing"], ["to compose a poem"])
LAUGH = _word("笑う", ["to laugh"], ["to smile"])
SLEEP = _word("眠る", ["to sleep"], ["to die", "to rest (in peace)"])
TALK = _word("話す", ["to talk", "to speak"], ["to tell", "to explain"])


# Wrong options for a word


def test_a_word_sharing_a_gloss_with_the_target_isnt_a_wrong_option():
    shout = _word("叫ぶ", ["to shout"], ["to call"])

    assert _forms(pick_wrong_options(CALL, [shout, SING, LAUGH, SLEEP])) == [
        "歌う",
        "笑う",
        "眠る",
    ]


def test_a_word_sharing_a_meaningful_word_with_the_target_isnt_a_wrong_option():
    # "calling" is call + ing.
    vocation = _word("励む", ["to follow a calling"], ["to strive"])

    assert "励む" not in _forms(pick_wrong_options(CALL, [vocation, SING, LAUGH]))


def test_a_word_shared_only_in_a_qualifier_doesnt_make_a_wrong_option_a_synonym():
    # Besides "to", which carries no meaning, they share only "ball", which
    # says where each applies rather than what it means.
    target = _word("投げる", ["to throw (a ball)"], ["to give up"])
    bounce = _word("弾む", ["to bounce (of a ball)"], ["to be lively"])

    assert _forms(pick_wrong_options(target, [bounce])) == ["弾む"]


def test_a_word_read_another_way_isnt_a_wrong_option():
    painful = _word("辛い", ["painful", "heart-breaking"], pos="形容詞")
    spicy = _word("辛い", ["spicy", "hot"], pos="形容詞")
    sweet = _word("甘い", ["sweet"], pos="形容詞")

    assert _forms(pick_wrong_options(painful, [spicy, sweet])) == ["甘い"]


def test_another_spelling_of_the_same_entry_isnt_a_wrong_option():
    pretty = _word("綺麗", ["pretty"], ["clean"], pos="形状詞")
    # Written in kana, with a gloss of its own so that only the entry gives
    # it away.
    respelled = WordSenses(
        "きれい", "形状詞", [{**pretty.senses[0], "gloss": ["neat"]}]
    )

    assert pick_wrong_options(pretty, [respelled]) == []


def test_no_two_wrong_options_share_a_meaning():
    cry = _word("泣く", ["to cry", "to weep"], ["to howl"])
    weep = _word("咽ぶ", ["to weep"], ["to be choked with tears"])

    picked = pick_wrong_options(CALL, [cry, weep, SING, LAUGH])

    assert _forms(picked) == ["泣く", "歌う", "笑う"]


def test_a_meaning_the_target_is_rarely_known_by_doesnt_rule_a_word_out():
    # Past the senses the reading view shows before "Show more".
    many = _word(
        "掛ける",
        ["to hang"],
        ["to put on"],
        ["to cover"],
        ["to spend"],
        ["to pour"],
        ["to sing"],
    )

    assert "歌う" in _forms(pick_wrong_options(many, [SING]))


def test_wrong_options_of_the_targets_part_of_speech_come_first():
    voice = _word("声", ["voice"], ["sound"], pos="名詞")
    you = _word("君", ["you"], ["monarch"], pos="代名詞")

    picked = pick_wrong_options(CALL, [voice, you, SING, LAUGH, SLEEP])

    assert _forms(picked) == ["歌う", "笑う", "眠る"]


def test_a_shorter_wrong_option_is_used_only_when_the_full_ones_run_out():
    cry = _word("泣く", ["to cry"])
    voice = _word("声", ["voice"], ["sound"], pos="名詞")

    assert _forms(pick_wrong_options(CALL, [cry, SING, LAUGH, SLEEP])) == [
        "歌う",
        "笑う",
        "眠る",
    ]
    # Shorter, but of the same part of speech, beats another part of speech.
    assert _forms(pick_wrong_options(CALL, [voice, cry, SING, LAUGH])) == [
        "歌う",
        "笑う",
        "泣く",
    ]


def test_a_part_of_speech_runs_out_into_any_other():
    voice = _word("声", ["voice"], ["sound"], pos="名詞")

    assert _forms(pick_wrong_options(CALL, [voice, SING])) == ["歌う", "声"]


def test_candidates_past_the_last_one_needed_arent_drawn():
    def candidates():
        yield from [SING, LAUGH, SLEEP]
        raise AssertionError("drew a fourth candidate")

    assert len(pick_wrong_options(CALL, candidates())) == 3


def test_every_option_shows_as_many_senses_as_the_targets_up_to_two():
    rng = random.Random(0)
    three = _word("話す", ["to talk"], ["to tell"], ["to release"])
    one = _word("泣く", ["to cry"])

    content = word_content(three, [SING, LAUGH, SLEEP], None, rng)
    assert [len(option.senses) for option in content.options] == [2, 2, 2, 2]
    assert content.options[content.answer].senses == [["to talk"], ["to tell"]]
    assert content.senses == three.senses

    content = word_content(one, [SING, LAUGH, SLEEP], None, rng)
    assert [len(option.senses) for option in content.options] == [1, 1, 1, 1]
    assert content.options[content.answer].senses == [["to cry"]]


def test_the_right_option_moves_around():
    answers = {
        word_content(TALK, [SING, LAUGH, SLEEP], None, random.Random(seed)).answer
        for seed in range(20)
    }

    assert answers == {0, 1, 2, 3}


def test_a_word_with_no_senses_left_has_no_options():
    content = word_content(_word("消えた"), [SING, LAUGH], None, random.Random(0))

    assert (content.options, content.answer) == ([], None)


# Wrong options for a grammar term


def _terms_by_note() -> dict[str, list[str]]:
    by_note: dict[str, list[str]] = {}
    for term, note in grammar_notes().items():
        by_note.setdefault(note, []).append(term)
    return by_note


@pytest.mark.parametrize("term", list(grammar_notes()))
def test_every_grammar_term_has_four_options_of_its_own_kind_none_alike(term):
    notes = grammar_notes()
    by_note = _terms_by_note()
    for seed in range(5):
        content = grammar_content(term, None, random.Random(seed))

        shown = [option.note for option in content.options]
        assert len(set(shown)) == OPTION_COUNT
        assert shown[content.answer] == notes[term]
        for note in shown:
            assert grammar_category(by_note[note][0]) == grammar_category(term)
        for first, second in itertools.combinations(shown, 2):
            assert not any(
                notes_overlap(a, b) for a in by_note[first] for b in by_note[second]
            )


def test_grammar_explained_alike_is_never_on_one_card():
    for terms in _terms_by_note().values():
        for a, b in itertools.combinations(terms, 2):
            assert notes_overlap(a, b), (a, b)


def test_every_term_said_to_overlap_has_an_explanation():
    notes = grammar_notes()
    for group in _OVERLAPPING_NOTES:
        assert group <= notes.keys(), group - notes.keys()


@pytest.mark.parametrize(
    "term, other, overlap",
    [
        # Both just "if".
        ("ば", "たら", True),
        ("から", "ので", True),
        ("よう", "みたい", True),
        # Quoting, and hearsay.
        ("って", "と", True),
        ("って", "そう", True),
        # The distinctions a card should test.
        ("を", "が", False),
        ("ば", "ても", False),
        ("よ", "ね", False),
        ("来る", "行く", False),
    ],
)
def test_grammar_explained_alike_overlaps(term, other, overlap):
    assert notes_overlap(term, other) == overlap
    assert notes_overlap(other, term) == overlap


# The line a card plays


def test_a_line_index_counts_the_line_breaks_before_it():
    lyrics = "君を呼ぶ\n\n声が聞こえる"

    assert [line_index(lyrics, offset) for offset in (0, 4, 5, 6, 8)] == [0, 0, 1, 2, 2]


def _card(cards, lookup_form: str):
    return next(card for card in cards if card.lookup_form == lookup_form)


def _span(line, span: tuple[int, int]) -> str:
    return line.text[span[0] : span[1]]


SONG = "君を呼ぶ。\n声が聞こえてるんだって。"


def test_a_words_card_plays_the_line_its_word_is_on(committed_engine):
    document_id = create_tokenized_document(SONG, title="song")

    line = _card(start_song_session(document_id).cards, "聞こえる").line

    assert (line.document_id, line.title, line.index) == (document_id, "song", 1)
    assert line.text == "声が聞こえてるんだって。"
    assert _span(line, line.focus) == "聞こえ"
    assert _span(line, line.group) == "聞こえてるんだって"
    assert line.token_id == document_tokens(document_id, "聞こえ")[0].id


def test_a_cards_line_has_the_furigana_of_its_kanji(committed_engine):
    document_id = create_tokenized_document(SONG)

    line = _card(start_song_session(document_id).cards, "聞こえる").line

    assert [(_span(line, (r.begin, r.end)), r.reading) for r in line.furigana] == [
        ("声", "こえ"),
        ("聞", "き"),
    ]


def test_a_grammar_cards_line_points_at_the_grammar_in_its_group(committed_engine):
    document_id = create_tokenized_document(SONG)

    line = _card(start_song_session(document_id).cards, "って").line

    assert _span(line, line.focus) == "って"
    assert _span(line, line.group) == "聞こえてるんだって"
    assert line.token_id == document_tokens(document_id, "って")[0].id


def test_an_accepted_phrases_card_points_at_the_whole_phrase(committed_engine):
    document_id = create_tokenized_document("真に受けてみて")
    [suggestion] = [
        c.id
        for t in get_document_tokens(document_id)
        for c in t.conflicts
        if c.kind == "phrase"
    ]
    accept_phrase_suggestions_endpoint(
        document_id, PhraseAcceptance(conflict_ids=[suggestion])
    )

    line = _card(start_song_session(document_id).cards, "真に受ける").line

    assert _span(line, line.focus) == "真に受け"
    assert _span(line, line.group) == "真に受けてみて"
    assert line.token_id == document_tokens(document_id, "真")[0].id


def test_a_word_sung_in_katakana_points_at_its_part_of_the_katakana(
    committed_engine,
):
    start_song_session(create_tokenized_document("僕を呼ぶ。会いたい。"))
    document_id = create_tokenized_document("君を呼ぶ。\nボクノアイタイ。")

    cards = start_song_session(document_id).cards

    line = _card(cards, "僕").line
    assert (line.document_id, line.index) == (document_id, 1)
    assert _span(line, line.focus) == "ボク"
    assert _span(line, line.group) == "ボクノアイタイ"
    assert line.written_as == "僕"
    line = _card(cards, "会う").line
    assert _span(line, line.focus) == "アイ"
    assert line.written_as == "会う"
    line = _card(cards, "たい").line
    assert _span(line, line.focus) == "タイ"
    assert line.written_as == "たい"
    # Not sung in katakana here.
    assert _card(cards, "呼ぶ").line.written_as is None


def _song_with_timings(
    engine, lyrics: str, timings, video: str | None = "video-id"
) -> int:
    """A tokenized song of `lyrics` on the YouTube video `video`, with
    LRCLIB's line `timings`."""
    document_id = create_document(
        DocumentCreate(title="test", text=lyrics, youtube_video_id=video)
    ).id
    get_document_tokens(document_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE documents SET lrclib_lines = CAST(:lines AS JSONB), lrclib_lines_text = text WHERE id = :id"
            ),
            {"id": document_id, "lines": json.dumps(timings)},
        )
    return document_id


def test_a_line_with_a_video_and_a_timing_plays(committed_engine):
    document_id = _song_with_timings(
        committed_engine, SONG, [{"start": 1.0, "end": 2.5}, {"start": 2.5, "end": 6.0}]
    )

    audio = _card(start_song_session(document_id).cards, "聞こえる").line.audio

    assert (audio.youtube_video_id, audio.start, audio.end) == ("video-id", 2.5, 6.0)


@pytest.mark.parametrize(
    "video, timings",
    [
        (None, [{"start": 1.0, "end": 2.5}, {"start": 2.5, "end": 6.0}]),
        ("video-id", None),
        ("video-id", [{"start": 1.0, "end": 2.5}]),
        ("video-id", [{"start": 1.0, "end": 2.5}, None]),
        # Sung at the same moment as the line before, so it has no length.
        ("video-id", [{"start": 1.0, "end": 1.0}, {"start": 1.0, "end": 1.0}]),
    ],
)
def test_a_line_without_a_video_or_a_timing_is_text_only(
    committed_engine, video, timings
):
    document_id = _song_with_timings(committed_engine, SONG, timings, video=video)

    line = _card(start_song_session(document_id).cards, "聞こえる").line

    assert line.audio is None
    assert line.text == "声が聞こえてるんだって。"


def test_edited_timings_are_played_over_lrclibs(committed_engine):
    document_id = _song_with_timings(
        committed_engine, SONG, [{"start": 1.0, "end": 2.5}, {"start": 2.5, "end": 6.0}]
    )
    save_line_timings(
        document_id,
        LineTimingsUpdate(
            text=SONG, lines=[{"start": 1.0, "end": 3.0}, {"start": 3.0, "end": 7.0}]
        ),
    )

    audio = _card(start_song_session(document_id).cards, "聞こえる").line.audio

    assert (audio.start, audio.end) == (3.0, 7.0)


def test_a_line_that_plays_is_chosen_over_one_that_doesnt(committed_engine):
    document_id = _song_with_timings(
        committed_engine, "君を呼ぶ\n\n君の声", [{"start": 1.0, "end": 2.0}, None, None]
    )

    # Either line would be chosen half the time at random.
    for _ in range(10):
        line = _card(start_song_session(document_id).cards, "君").line
        assert (line.index, line.audio.start) == (0, 1.0)


def test_the_all_songs_queue_plays_a_line_from_a_song_with_the_word(
    committed_engine,
):
    first = create_tokenized_document("君を呼ぶ。", title="first")
    create_tokenized_document("泣く。話す。", title="second")
    start_song_session(first)

    line = _card(get_all_songs_queue().cards, "呼ぶ").line

    assert (line.document_id, line.title, line.text) == (first, "first", "君を呼ぶ。")


def test_a_card_in_no_song_has_no_line_but_can_still_be_answered(committed_engine):
    gone = create_tokenized_document("君を呼ぶ。")
    kept = create_tokenized_document("歌う。笑う。眠る。話す。")
    start_song_session(gone)
    start_song_session(kept)
    with committed_engine.begin() as conn:
        conn.execute(text("DELETE FROM tokens WHERE document_id = :id"), {"id": gone})

    card = _card(get_all_songs_queue().cards, "呼ぶ")

    assert card.line is None
    assert len(card.options) == OPTION_COUNT
    assert card.options[card.answer].senses[0] == card.senses[0].gloss


# A queued card's options


def _first_glosses(card) -> set[str]:
    return {option.senses[0][0] for option in card.options}


def test_the_right_option_is_the_words_top_ranked_senses(committed_engine):
    document_id = create_tokenized_document(SONG)

    card = _card(start_song_session(document_id).cards, "聞こえる")

    assert card.options[card.answer].senses == [
        ["to be heard", "to be audible"],
        ["to be said to be", "to be reputed"],
    ]
    assert [sense.gloss for sense in card.senses] == card.options[card.answer].senses


def test_a_words_wrong_options_come_from_its_own_song(committed_engine):
    document_id = create_tokenized_document("歌う。笑う。泣く。眠る。探す。話す。")

    card = _card(start_song_session(document_id).cards, "歌う")

    assert len(card.options) == OPTION_COUNT
    assert _first_glosses(card) <= {
        "to sing",
        "to laugh",
        "to sleep",
        "to search for",
        "to talk",
    }
    # 泣く has a single sense; there are enough with two.
    assert all(len(option.senses) == 2 for option in card.options)


def test_a_song_short_of_words_borrows_wrong_options_from_the_users_others(
    committed_engine,
):
    other = create_tokenized_document("歌う。笑う。眠る。話す。")
    start_song_session(other)
    document_id = create_tokenized_document("君を呼ぶ。")

    card = _card(start_song_session(document_id).cards, "呼ぶ")

    # The song's only other word is a pronoun, 君.
    assert len(card.options) == OPTION_COUNT
    assert _first_glosses(card) <= {
        "to call out (to)",
        "to sing",
        "to laugh",
        "to sleep",
        "to talk",
    }


def test_options_are_looked_up_again_after_the_gloss_cache_is_emptied(
    committed_engine,
):
    document_id = create_tokenized_document("歌う。笑う。眠る。話す。")
    start_song_session(document_id)
    empty_gloss_cache()

    card = _card(start_song_session(document_id).cards, "歌う")

    assert len(card.options) == OPTION_COUNT
    assert card.options[card.answer].senses[0] == ["to sing"]


def test_a_grammar_cards_options_are_notes_and_its_own_is_right(committed_engine):
    document_id = create_tokenized_document(SONG)

    card = _card(start_song_session(document_id).cards, "って")

    assert len(card.options) == OPTION_COUNT
    assert card.options[card.answer].note == grammar_notes()["って"]
    assert all(option.senses is None for option in card.options)
    assert card.senses == []
