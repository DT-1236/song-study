"""Which of a document's words become study cards, and enrolling them."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.cards import (
    CardKey,
    document_card_keys,
    document_units,
    enroll_new_words,
    gloss_sources,
    harvest,
)
from app.main import TokensIgnored
from tests.fixtures import amazing_grace
from tests.support import (
    TEST_USER_ID,
    accept_phrase_suggestion,
    add_token_card,
    as_user,
    clear_gloss_links,
    create_tokenized_document,
    document_tokens,
    empty_gloss_cache,
    get_document_tokens,
    get_document_words,
    grammar_key,
    pick_reading,
    set_tokens_ignored,
    suspend_card,
    user_cards,
    word_key,
)


def _harvest(engine, document_id: int) -> dict[CardKey, int]:
    """Each word the document harvests for the test user, with how often it
    occurs."""
    with engine.begin() as conn:
        return {
            w.key: w.occurrences
            for w in harvest(conn, document_units(conn, document_id), TEST_USER_ID)
        }


def _enroll(engine, document_id: int, limit: int | None = None) -> list[CardKey]:
    """The words enroll_new_words gave the test user new cards for."""
    with engine.begin() as conn:
        ids = enroll_new_words(conn, TEST_USER_ID, document_id, limit)
        rows = conn.execute(
            text(
                "SELECT kind, lookup_form, reading FROM study_cards WHERE id = ANY(:ids) ORDER BY id"
            ),
            {"ids": ids},
        ).all()
    return [CardKey(*row) for row in rows]


# The harvest


def test_a_predicate_group_gives_its_head_word_and_itsgrammar_key(committed_engine):
    # 声 is left out as an unreviewed heteronym; see below.
    document_id = create_tokenized_document(text="君の声が聞こえてるんだって。")

    assert _harvest(committed_engine, document_id) == {
        word_key("君", "きみ"): 1,
        # As the verb it is, not as the group's composite gloss.
        word_key("聞こえる", "きこえる"): 1,
        grammar_key("てる"): 1,
        # ん, as Sudachi normalizes it when it explains.
        grammar_key("の"): 1,
        grammar_key("だ"): 1,
        grammar_key("って"): 1,
    }


def test_particles_outside_a_group_give_nothing(committed_engine):
    document_id = create_tokenized_document(text="君を呼ぶ。")

    assert _harvest(committed_engine, document_id) == {
        word_key("君", "きみ"): 1,
        word_key("呼ぶ", "よぶ"): 1,
    }


def test_a_word_counts_every_occurrence_under_one_card(committed_engine):
    document_id = create_tokenized_document(text="聞こえてる。聞こえた。")

    assert _harvest(committed_engine, document_id) == {
        word_key("聞こえる", "きこえる"): 2,
        grammar_key("てる"): 1,
        grammar_key("た"): 1,
    }


def test_a_word_without_a_jmdict_headword_is_left_out(committed_engine):
    # An English word, and a proper noun only glossed through its parts.
    document_id = create_tokenized_document(text="yeah ゲーム、女神の涙")

    assert _harvest(committed_engine, document_id) == {word_key("ゲーム", "ゲーム"): 1}


def test_english_lyrics_give_nothing(committed_engine):
    # Even the words Sudachi normalizes to katakana that JMDict has (How
    # -> ハウ, now -> ナウ).
    document_id = create_tokenized_document(text=amazing_grace.TEXT)

    assert _harvest(committed_engine, document_id) == {}


def test_a_word_marked_as_needing_no_gloss_is_left_out(committed_engine):
    document_id = create_tokenized_document(text="君を呼ぶ。")
    set_tokens_ignored(
        document_id,
        TokensIgnored(
            token_ids=[document_tokens(document_id, "君")[0].id], ignored=True
        ),
    )

    assert _harvest(committed_engine, document_id) == {word_key("呼ぶ", "よぶ"): 1}


def test_a_heteronym_is_harvested_under_its_reading_once_one_is_picked(
    committed_engine,
):
    document_id = create_tokenized_document(text="今日は")
    assert _harvest(committed_engine, document_id) == {}

    pick_reading(document_id, "今日", "こんにち")

    assert _harvest(committed_engine, document_id) == {word_key("今日", "こんにち"): 1}


def test_picking_the_default_reading_also_counts_as_reviewing_it(committed_engine):
    document_id = create_tokenized_document(text="今日は")

    pick_reading(document_id, "今日", "きょう")

    assert _harvest(committed_engine, document_id) == {word_key("今日", "きょう"): 1}


@pytest.mark.parametrize(
    "reason, harvested",
    [
        # Its reading is certain; only how it spreads over the kanji isn't.
        ("no_kana_anchor", True),
        # A reading nothing in the dictionary backs.
        ("oov", False),
    ],
)
def test_an_unreviewed_token_is_harvested_only_if_its_reading_is_certain(
    committed_engine, reason, harvested
):
    document_id = create_tokenized_document(text="君")
    with committed_engine.begin() as conn:
        conn.execute(
            text("UPDATE tokens SET needs_review = TRUE, review_reason = :reason"),
            {"reason": reason},
        )

    assert bool(_harvest(committed_engine, document_id)) == harvested


def test_an_accepted_phrase_is_one_word_with_its_attachedgrammar_key(committed_engine):
    document_id = create_tokenized_document(text="真に受けてみて")
    # 真 is an unreviewed heteronym on its own.
    assert _harvest(committed_engine, document_id) == {
        word_key("受ける", "うける"): 1,
        grammar_key("て"): 2,
        grammar_key("見る"): 1,
    }

    accept_phrase_suggestion(document_id)

    # The phrase's own に is part of the headword, not grammar.
    assert _harvest(committed_engine, document_id) == {
        word_key("真に受ける", "まにうける"): 1,
        grammar_key("て"): 2,
        grammar_key("見る"): 1,
    }


def test_an_accepted_phrase_with_a_member_marked_as_needing_no_gloss_is_left_out(
    committed_engine,
):
    document_id = create_tokenized_document(text="真に受けてみて")
    accept_phrase_suggestion(document_id)
    phrase = word_key("真に受ける", "まにうける")
    assert phrase in _harvest(committed_engine, document_id)
    set_tokens_ignored(
        document_id,
        TokensIgnored(
            token_ids=[document_tokens(document_id, "真")[0].id], ignored=True
        ),
    )

    harvested = _harvest(committed_engine, document_id)
    # Still accepted, so it's the ignored member that leaves it out.
    assert get_document_tokens(document_id)[0].group_kind == "phrase"
    assert phrase not in harvested
    assert harvested


def test_a_harvest_after_the_gloss_cache_is_emptied_looks_its_words_up_again(
    committed_engine,
):
    # さり気ない's normalized form, さり気無い, has no JMDict entry: only its
    # dictionary form, the alternate spelling, finds one.
    document_id = create_tokenized_document(
        text="さり気ない歌を。君の声が聞こえてるんだって。"
    )
    before = _harvest(committed_engine, document_id)
    assert word_key("さり気無い", "さりげない") in before

    empty_gloss_cache()

    assert _harvest(committed_engine, document_id) == before


# A line sung in katakana

KATAKANA_SONG = "ボクノアイタイ。"


def _song_keys(engine, document_id: int) -> set[CardKey]:
    with engine.begin() as conn:
        return document_card_keys(conn, document_units(conn, document_id))


def test_a_katakana_word_belongs_to_the_cards_of_the_words_it_splits_into(
    committed_engine,
):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    assert get_document_tokens(document_id)[0].surface == "ボクノアイタイ"

    assert _song_keys(committed_engine, document_id) == {
        word_key("僕", "ぼく"),
        # Written as its gloss writes it, so it's the card 会いたい gives.
        word_key("会う", "あう"),
        # Attached to 会う. The の between the two words is grammar on its
        # own, which gives nothing.
        grammar_key("たい"),
    }


def test_a_katakana_word_harvests_nothing(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)

    assert _harvest(committed_engine, document_id) == {}


def test_a_katakana_word_unlinked_from_its_gloss_links_to_no_card(committed_engine):
    document_id = create_tokenized_document(text=KATAKANA_SONG)
    clear_gloss_links(document_id)

    assert not _song_keys(committed_engine, document_id) & {
        word_key("僕", "ぼく"),
        word_key("会う", "あう"),
        grammar_key("たい"),
    }


# Storage


def test_a_cards_gloss_is_looked_up_again_after_the_cache_is_emptied(
    committed_engine,
):
    document_id = create_tokenized_document(text="さり気ない")
    _enroll(committed_engine, document_id)
    empty_gloss_cache()

    [card] = user_cards().values()
    key = (card.lookup_form, card.reading)
    with committed_engine.begin() as conn:
        source = gloss_sources(conn, [(key, card.alt_lookup_form)])[key]

    assert source == "jmdict"


def test_emptying_the_gloss_cache_keeps_every_card(committed_engine):
    document_id = create_tokenized_document(text="君の声が聞こえてるんだって。")
    enrolled = _enroll(committed_engine, document_id)

    empty_gloss_cache()

    assert set(user_cards()) == set(enrolled)


def test_a_card_with_reviews_cant_be_deleted(committed_engine):
    document_id = create_tokenized_document(text="君")
    _enroll(committed_engine, document_id)
    [card] = user_cards().values()
    with committed_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO study_reviews (card_id, document_id, correct, duration_ms, fast_ms, slow_ms, rating)
                VALUES (:card_id, :document_id, TRUE, 2000, 3000, 10000, 3)
                """
            ),
            {"card_id": card.id, "document_id": document_id},
        )

    with pytest.raises(IntegrityError), committed_engine.begin() as conn:
        conn.execute(text("DELETE FROM study_cards WHERE id = :id"), {"id": card.id})


# Enrolling


def test_enrolling_creates_new_cards_for_the_most_common_words_first(
    committed_engine,
):
    document_id = create_tokenized_document(text="君を呼ぶ。聞こえてる。聞こえた。")

    first = _enroll(committed_engine, document_id, limit=3)
    rest = _enroll(committed_engine, document_id)

    # Grammar terms first; then 君, which JMDict marks common without an nf
    # band, ahead of 呼ぶ (nf02) and 聞こえる (nf25) though 聞こえる is sung
    # twice.
    assert first == [grammar_key("てる"), grammar_key("た"), word_key("君", "きみ")]
    assert rest == [word_key("呼ぶ", "よぶ"), word_key("聞こえる", "きこえる")]
    assert _enroll(committed_engine, document_id) == []


def test_a_new_card_starts_unscheduled_and_remembers_its_song(committed_engine):
    document_id = create_tokenized_document(text="君")
    _enroll(committed_engine, document_id)

    [card] = user_cards().values()
    # py-fsrs's new card: Learning, at its first step.
    assert (card.state, card.step, card.stability, card.difficulty) == (
        1,
        0,
        None,
        None,
    )
    assert card.last_review is None
    assert not card.suspended
    assert card.first_seen_document_id == document_id


def test_a_word_already_carded_from_another_song_is_not_new(committed_engine):
    first_song = create_tokenized_document(text="君を呼ぶ。")
    second_song = create_tokenized_document(text="君の声")
    _enroll(committed_engine, first_song)

    assert _enroll(committed_engine, second_song) == []
    assert user_cards()[word_key("君", "きみ")].first_seen_document_id == (first_song)


def test_each_user_has_their_own_cards(committed_engine, other_user):
    mine = create_tokenized_document(text="君")
    with as_user(other_user):
        theirs = create_tokenized_document(text="君")
    _enroll(committed_engine, mine)

    with committed_engine.begin() as conn:
        enroll_new_words(conn, other_user, theirs)

    assert set(user_cards()) == set(user_cards(other_user))


# Adding a word by hand


def test_adding_a_word_by_hand_takes_an_unreviewed_reading(committed_engine):
    document_id = create_tokenized_document(text="今日は")

    card = add_token_card(document_id, document_tokens(document_id, "今日")[0].id)

    assert (card.kind, card.lookup_form, card.reading) == (
        "recognition",
        "今日",
        "きょう",
    )
    assert card.first_seen_document_id == document_id


def test_adding_a_word_by_hand_takes_one_marked_as_needing_no_gloss(
    committed_engine,
):
    document_id = create_tokenized_document(text="君")
    token_id = document_tokens(document_id, "君")[0].id
    set_tokens_ignored(document_id, TokensIgnored(token_ids=[token_id], ignored=True))

    assert add_token_card(document_id, token_id).lookup_form == "君"


def test_adding_any_token_of_a_predicate_group_adds_its_headword_key(committed_engine):
    document_id = create_tokenized_document(text="聞こえてるんだって")

    card = add_token_card(document_id, document_tokens(document_id, "って")[0].id)

    assert (card.lookup_form, card.reading) == ("聞こえる", "きこえる")


@pytest.mark.parametrize("surface", ["を", "yeah", "女神の涙", "。"])
def test_a_token_that_isnt_a_word_with_a_headword_cant_be_added(
    committed_engine, surface
):
    document_id = create_tokenized_document(text="女神の涙を。yeah")

    with pytest.raises(HTTPException) as exc:
        add_token_card(document_id, document_tokens(document_id, surface)[0].id)

    assert exc.value.status_code == 422
    assert user_cards() == {}


def test_adding_another_documents_token_is_refused(committed_engine):
    document_id = create_tokenized_document(text="君")
    other_id = create_tokenized_document(text="君")

    with pytest.raises(HTTPException) as exc:
        add_token_card(document_id, document_tokens(other_id, "君")[0].id)

    assert exc.value.status_code == 404


def _grammar_words(document_id: int):
    return [w for w in get_document_words(document_id) if w.kind == "grammar"]


def test_a_predicate_groups_grammar_can_be_added_removed_and_restored(
    committed_engine,
):
    document_id = create_tokenized_document(text="聞こえてるんだって")
    group_gloss = get_document_tokens(document_id)[0].gloss
    [word] = [w for w in _grammar_words(document_id) if w.lookup_form == "って"]
    # The grammar's piece is where the group's gloss lists it.
    assert group_gloss.pieces[word.piece].surface == "って"
    assert word.card is None

    card = add_token_card(document_id, word.token_ids[0], piece=word.piece)
    assert (card.kind, card.lookup_form, card.reading) == ("grammar", "って", None)

    suspend_card(card.id)
    [again] = [w for w in _grammar_words(document_id) if w.lookup_form == "って"]
    assert again.card.suspended
    restored = add_token_card(document_id, word.token_ids[0], piece=word.piece)
    assert (restored.id, restored.suspended) == (card.id, False)


def test_a_piece_that_isnt_a_word_or_grammar_of_a_group_cant_be_added(
    committed_engine,
):
    document_id = create_tokenized_document(text="聞こえてるんだって")
    token_id = document_tokens(document_id, "って")[0].id

    with pytest.raises(HTTPException) as exc:
        add_token_card(document_id, token_id, piece=0)

    assert exc.value.status_code == 422
    assert user_cards() == {}


def test_grammar_isnt_offered_while_its_groups_gloss_is_unlinked(committed_engine):
    document_id = create_tokenized_document(text="聞こえてるんだって")
    clear_gloss_links(document_id)

    words = get_document_words(document_id)

    # With no gloss to place it in, it has no piece, which would make it
    # look like the group's own word.
    assert [(w.kind, w.piece) for w in words] == [("recognition", None)]
