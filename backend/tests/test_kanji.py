"""The kanji sidebar's data: which readings a word uses of each kanji, the
radical it contains, and the words of the deck it's in. Every failure here
looks plausible on screen, so each is pinned by a case."""

from __future__ import annotations

from unicodedata import normalize

from sqlalchemy import text

from app.glosses import get_jamdict
from app.kanji import (
    _RADICAL_VARIANTS,
    MAX_COMPONENTS,
    MAX_DECK_WORDS,
    _kun_in_play,
    card_kanji,
    deck_cards,
    kanji_entries,
    kanji_in_spans,
    kanji_in_word,
)
from app.tokenization import furigana_spans_for_reading
from tests.support import (
    TEST_USER_ID,
    create_tokenized_document,
    get_all_songs_queue,
    start_song_session,
)


def _used(word: str, reading: str, dictionary_form: str | None = None):
    """The kanji of `word`, an inflection of `dictionary_form`, as it uses
    them."""
    spans = furigana_spans_for_reading(word, reading)
    return _card_kanji(kanji_in_spans(spans, dictionary_form or word))


def _card_kanji(kanji):
    """`card_kanji` of `kanji`, given the entries a queue would have for them."""
    return card_kanji(kanji, kanji_entries({k.character for k in kanji}, {}))


def _use(word: str, reading: str, character: str, dictionary_form: str | None = None):
    return next(
        k for k in _used(word, reading, dictionary_form) if k.character == character
    )


def _entry(character: str):
    """The sidebar entry of `character`, with no deck."""
    return kanji_entries([character], {})[character]


# Which kun reading a word uses


def test_a_kun_reading_matches_past_its_okurigana_marker():
    # 聞 has き.く and き.こえる; 聞こえてる is the second.
    assert _use("聞こえてる", "キコエテル", "聞", "聞こえる").kun_readings == [
        "き(こえる)"
    ]


def test_an_inflection_that_changes_the_okurigana_still_matches_its_dictionary_forms():
    # 聞いた no longer has the く of 聞く.
    assert _use("聞いた", "キイタ", "聞", "聞く").kun_readings == ["き(く)"]


def test_kun_readings_the_word_doesnt_use_are_counted_not_listed():
    use = _use("聞こえる", "キコエル", "聞")

    assert use.kun_readings == ["き(こえる)"]
    assert use.more_kun == 1


def test_a_rendaku_reading_matches_the_unvoiced_kun_reading():
    # 女神 reads 神 as がみ, which KANJIDIC2 lists as かみ.
    assert _use("女神", "メガミ", "神").kun_readings == ["かみ"]


def test_a_reading_matching_a_voiced_kun_reading_isnt_unvoiced():
    kun = ["とお.る", "-どお.り"]

    assert _kun_in_play(kun, "どお", "り") == ["-どお.り"]


def test_a_kun_readings_hyphen_is_dropped_before_comparing():
    assert _kun_in_play(["かん-"], "かん", "") == ["かん-"]


def test_a_readings_script_doesnt_matter():
    hiragana = _card_kanji(kanji_in_word("聞こえる", "きこえる"))
    katakana = _card_kanji(kanji_in_word("聞こえる", "キコエル"))

    assert hiragana == katakana
    assert hiragana[0].kun_readings == ["き(こえる)"]


def test_a_kanji_read_by_on_yomi_lists_no_kun_reading():
    assert _use("新聞", "シンブン", "聞").kun_readings == []


def test_a_word_read_as_a_whole_gives_its_kanji_no_reading():
    # 今日 is きょう, which isn't any one kanji's.
    kanji = kanji_in_word("今日", "きょう")

    assert [(k.character, k.reading) for k in kanji] == [("今", None), ("日", None)]
    assert all(k.kun_readings == [] for k in _used("今日", "キョウ"))


# What's shown of a kanji


def test_every_on_reading_is_listed_with_the_grade_and_frequency():
    entry = _entry("聞")

    assert entry.on_readings == ["ブン", "モン"]
    assert (entry.grade, entry.frequency) == (2, 319)
    assert entry.meanings[:3] == ["hear", "ask", "listen"]


def test_meanings_are_in_english_only():
    # KANJIDIC2 also has French, Spanish and Portuguese.
    assert "entendre" not in _entry("聞").meanings


def test_the_radical_is_the_form_the_kanji_contains():
    assert _entry("涙").radical.character == "氵"
    assert _entry("神").radical.character == "礻"
    assert _entry("通").radical.character == "辶"


def test_every_radical_variant_is_a_component_krad_file_has():
    # A variant KRADFILE never writes would never be found, and its kanji
    # would show the standalone radical.
    components = {
        normalize("NFC", c) for parts in get_jamdict().krad.values() for c in parts
    }

    missing = [
        v for vs in _RADICAL_VARIANTS.values() for v in vs if v not in components
    ]

    assert missing == []


def test_the_radical_is_named_for_its_classical_form():
    assert _entry("涙").radical.meaning == "water"
    assert _entry("聞").radical.meaning == "ear"


def test_a_radical_is_its_own_form_where_the_kanji_contains_it_as_it_is():
    assert _entry("聞").radical.character == "耳"


def test_the_other_components_leave_out_the_radical_and_bare_strokes():
    # KRADFILE has 涙 as 戸, 氵, 大, 一 and 尸.
    components = _entry("涙").components

    assert components == ["戸", "大", "尸"]
    assert _entry("聞").components == ["門"]


def test_other_components_are_capped():
    entries = kanji_entries("新聞", {})

    assert all(len(e.components) <= MAX_COMPONENTS for e in entries.values())


def test_a_character_with_no_entry_is_left_out():
    # 々 stands for the kanji before it.
    assert [k.character for k in _used("人々", "ヒトビト")] == ["人"]
    assert list(kanji_entries("人々", {})) == ["人"]


def test_a_kanji_a_word_has_twice_is_listed_once():
    assert [k.character for k in _used("時時", "トキドキ")] == ["時"]


def test_a_word_with_no_kanji_has_none():
    assert _used("あなた", "アナタ") == []


# The deck


def _insert_card(conn, lookup_form: str, **columns) -> int:
    row = {
        "kind": "recognition",
        "reading": "よみ",
        "state": 1,
        "suspended": False,
        "last_review": None,
        "stability": None,
        **columns,
    }
    return conn.execute(
        text(
            """
            INSERT INTO study_cards
                (user_id, kind, lookup_form, reading, state, suspended, last_review,
                 stability)
            VALUES (:user_id, :kind, :lookup_form, :reading, :state, :suspended,
                    :last_review, :stability)
            RETURNING id
            """
        ),
        {"user_id": TEST_USER_ID, "lookup_form": lookup_form, **row},
    ).scalar_one()


def test_a_kanji_lists_the_deck_words_it_is_in_shortest_first(db_conn):
    _insert_card(db_conn, "新聞記事")
    _insert_card(db_conn, "新聞")
    _insert_card(db_conn, "歌う", reading="うたう")

    deck = deck_cards(db_conn, TEST_USER_ID, ["聞", "歌"])

    assert [word.lookup_form for word in deck["聞"]] == ["新聞", "新聞記事"]
    assert [word.lookup_form for word in deck["歌"]] == ["歌う"]


def test_a_deck_word_is_new_learning_or_mature(db_conn):
    _insert_card(db_conn, "聞a")
    _insert_card(db_conn, "聞b", last_review="2026-01-01", state=1, stability=1.0)
    _insert_card(db_conn, "聞c", last_review="2026-01-01", state=2, stability=10.0)
    _insert_card(db_conn, "聞d", last_review="2026-01-01", state=2, stability=21.0)
    _insert_card(db_conn, "聞e", last_review="2026-01-01", state=3, stability=40.0)

    deck = deck_cards(db_conn, TEST_USER_ID, ["聞"])

    assert {word.lookup_form: word.status for word in deck["聞"]} == {
        "聞a": "new",
        "聞b": "learning",
        "聞c": "learning",
        "聞d": "mature",
        "聞e": "learning",
    }


def test_a_removed_or_another_users_or_grammar_card_isnt_a_deck_word(
    committed_engine, other_user
):
    with committed_engine.begin() as conn:
        _insert_card(conn, "聞く", suspended=True)
        _insert_card(conn, "聞き", kind="grammar", reading=None)
        conn.execute(
            text(
                "INSERT INTO study_cards (user_id, kind, lookup_form, reading) "
                "VALUES (:user_id, 'recognition', '聞こえる', 'きこえる')"
            ),
            {"user_id": other_user},
        )

        assert deck_cards(conn, TEST_USER_ID, ["聞"]) == {}


def test_a_kanji_lists_one_more_deck_word_than_the_sidebar_shows(db_conn):
    # So that five are left once the card it's shown on is left out.
    for i in range(10):
        _insert_card(db_conn, f"聞{i}")

    deck = deck_cards(db_conn, TEST_USER_ID, ["聞"])

    assert len(deck["聞"]) == MAX_DECK_WORDS + 1


# A queued card


def test_a_cards_kanji_are_those_of_its_group_as_the_line_reads_them(
    committed_engine,
):
    document_id = create_tokenized_document("声が聞こえてるんだって。")

    cards = start_song_session(document_id).cards
    card = next(c for c in cards if c.lookup_form == "聞こえる")

    assert [(e.character, e.kun_readings) for e in card.kanji] == [
        ("聞", ["き(こえる)"])
    ]


def test_a_grammar_cards_kanji_are_those_of_the_group_it_is_in(committed_engine):
    document_id = create_tokenized_document("声が聞こえてるんだって。")

    cards = start_song_session(document_id).cards
    card = next(c for c in cards if c.lookup_form == "って")

    assert [e.character for e in card.kanji] == ["聞"]


def test_a_kanji_lists_the_other_words_in_the_deck_that_have_it(committed_engine):
    start_song_session(create_tokenized_document("新聞が好き。"))
    document_id = create_tokenized_document("声が聞こえる。")

    queue = start_song_session(document_id)
    card = next(c for c in queue.cards if c.lookup_form == "聞こえる")

    [used] = card.kanji
    deck_words = queue.kanji[used.character].deck_words
    # The card it's shown on too, which the sidebar leaves out by its id.
    assert [(w.lookup_form, w.card_id == card.id) for w in deck_words] == [
        ("新聞", False),
        ("聞こえる", True),
    ]


def test_every_kanji_a_card_has_is_in_the_queues_entries(committed_engine):
    queue = start_song_session(create_tokenized_document("声が聞こえて、新聞を読む。"))

    having = [c for c in queue.cards if "聞" in [k.character for k in c.kanji]]

    assert len(having) >= 2
    assert {k.character for c in queue.cards for k in c.kanji} == set(queue.kanji)


def test_a_card_in_no_song_has_the_kanji_of_its_key(committed_engine):
    gone = create_tokenized_document("君を呼ぶ。")
    start_song_session(gone)
    with committed_engine.begin() as conn:
        conn.execute(text("DELETE FROM tokens WHERE document_id = :id"), {"id": gone})

    card = next(c for c in get_all_songs_queue().cards if c.lookup_form == "呼ぶ")

    assert [(e.character, e.kun_readings) for e in card.kanji] == [("呼", ["よ(ぶ)"])]


def test_a_word_sung_in_katakana_has_the_kanji_of_the_word_it_is(committed_engine):
    start_song_session(create_tokenized_document("僕を呼ぶ。会いたい。"))
    cards = start_song_session(
        create_tokenized_document("君を呼ぶ。\nボクノアイタイ。")
    ).cards

    card = next(c for c in cards if c.lookup_form == "会う")

    assert [e.character for e in card.kanji] == ["会"]
