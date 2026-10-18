"""Scheduling study cards: rating an answer, reviewing, pushing a card out,
removing it, the queues, and the settings."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fsrs import Rating
from pydantic import ValidationError
from sqlalchemy import text

from app import study
from app.main import (
    PushOut,
    ReviewAnswer,
    SongStudySettings,
    StudySettings,
)
from app.study import rating_for
from tests.support import (
    TEST_USER_ID,
    BackgroundCall,
    add_token_card,
    as_user,
    create_tokenized_document,
    document_tokens,
    get_all_songs_queue,
    get_song_study_settings,
    get_study_settings,
    push_out_card,
    review_card,
    save_song_study_settings,
    save_study_settings,
    start_song_session,
    suspend_card,
    wait_for_lock_wait,
)

SONG = "君を呼ぶ。聞こえてる。聞こえた。"
# In the order they enroll: most sung first, then in order of appearance.
SONG_WORDS = ["聞こえる", "君", "呼ぶ", "てる", "た"]


def _lookup_forms(cards) -> list[str]:
    return [card.lookup_form for card in cards]


def _row(engine, card_id: int):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM study_cards WHERE id = :id"), {"id": card_id}
        ).one()


def _reviews(engine, card_id: int) -> list:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM study_reviews WHERE card_id = :id ORDER BY id"),
            {"id": card_id},
        ).all()


def _new_card(text_: str = "君") -> int:
    """The id of a new card for the only word of a document of `text_`."""
    [card] = start_song_session(create_tokenized_document(text_)).cards
    return card.id


def _set(engine, card_id: int, **columns) -> None:
    """Set columns of a card directly. A value is SQL, so `now() - interval
    '3 days'` works as well as a number."""
    assignments = ", ".join(f"{name} = {value}" for name, value in columns.items())
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE study_cards SET {assignments} WHERE id = :id"),
            {"id": card_id},
        )


def _known_for_30_days(engine, card_id: int) -> None:
    """Make the card a Review card last recalled 30 days ago with a stability
    of 30 days, so it's due now."""
    _set(
        engine,
        card_id,
        state=2,
        step="NULL",
        stability=30,
        difficulty=5,
        last_review="now() - interval '30 days'",
        due="now()",
    )


def _seconds_from_now(moment: datetime) -> float:
    return (moment - datetime.now(UTC)).total_seconds()


def _days_from_now(moment: datetime) -> float:
    return _seconds_from_now(moment) / 86_400


# Rating an answer


@pytest.mark.parametrize(
    "correct, duration_ms, multiple_choice, expected",
    [
        (False, 500, False, Rating.Again),
        (False, 500, True, Rating.Again),
        (False, 20_000, True, Rating.Again),
        (True, 20_000, False, Rating.Hard),
        (True, 20_000, True, Rating.Hard),
        (True, 5_000, False, Rating.Good),
        (True, 5_000, True, Rating.Good),
        (True, 500, False, Rating.Easy),
        # A four-option card can be guessed, so it never earns Easy.
        (True, 500, True, Rating.Good),
        # Neither threshold is itself fast or slow.
        (True, 3_000, False, Rating.Good),
        (True, 10_000, False, Rating.Good),
    ],
)
def test_an_answer_is_rated_by_correctness_and_latency(
    correct, duration_ms, multiple_choice, expected
):
    assert rating_for(correct, duration_ms, 3_000, 10_000, multiple_choice) == expected


# Reviewing


def test_a_correct_answer_moves_a_new_card_to_its_next_learning_step(
    committed_engine,
):
    card_id = _new_card()

    result = review_card(card_id, ReviewAnswer(correct=True, duration_ms=5_000))

    assert result.rating == Rating.Good
    # py-fsrs's default second learning step.
    assert 9 * 60 < _seconds_from_now(result.card.due) < 11 * 60
    row = _row(committed_engine, card_id)
    assert (row.state, row.step) == (1, 1)
    assert row.stability is not None and row.difficulty is not None
    assert row.last_review is not None


def test_a_wrong_answer_returns_a_new_card_to_its_first_step(committed_engine):
    card_id = _new_card()

    result = review_card(card_id, ReviewAnswer(correct=False, duration_ms=5_000))

    assert result.rating == Rating.Again
    assert 0 < _seconds_from_now(result.card.due) < 2 * 60
    assert _row(committed_engine, card_id).step == 0


def test_a_fast_answer_to_a_multiple_choice_card_is_only_good(committed_engine):
    # The rating table is covered above; this checks the route rates a
    # card as multiple choice.
    card_id = _new_card()

    assert review_card(card_id, ReviewAnswer(correct=True, duration_ms=0)).rating == (
        Rating.Good
    )


def test_a_review_is_logged_with_the_thresholds_it_was_rated_with(committed_engine):
    document_id = create_tokenized_document("君")
    [card] = start_song_session(document_id).cards

    review_card(
        card.id,
        ReviewAnswer(correct=True, duration_ms=4_321, document_id=document_id),
    )

    [review] = _reviews(committed_engine, card.id)
    assert (
        review.document_id,
        review.correct,
        review.duration_ms,
        review.fast_ms,
        review.slow_ms,
        review.rating,
    ) == (document_id, True, 4_321, 3_000, 10_000, 3)


def test_a_grammar_card_is_reviewed_the_same_way(committed_engine):
    document_id = create_tokenized_document(SONG)
    grammar = next(
        card for card in start_song_session(document_id).cards if card.kind == "grammar"
    )

    result = review_card(grammar.id, ReviewAnswer(correct=True, duration_ms=500))

    assert result.rating == Rating.Good


def test_a_graduated_card_is_scheduled_days_out(committed_engine):
    card_id = _new_card()
    _known_for_30_days(committed_engine, card_id)

    result = review_card(card_id, ReviewAnswer(correct=True, duration_ms=5_000))

    # Recalled after its stability: the next interval is longer than that.
    assert _days_from_now(result.card.due) > 30
    assert _row(committed_engine, card_id).state == 2


def test_a_lapse_puts_a_graduated_card_back_into_relearning(committed_engine):
    card_id = _new_card()
    _known_for_30_days(committed_engine, card_id)

    review_card(card_id, ReviewAnswer(correct=False, duration_ms=5_000))

    row = _row(committed_engine, card_id)
    assert row.state == 3
    assert row.stability < 30


def test_a_lower_desired_retention_spaces_reviews_further_apart(committed_engine):
    intervals = {}
    for retention in (0.75, 0.95):
        save_study_settings(StudySettings(desired_retention=retention))
        card_id = _new_card("君" if retention == 0.75 else "泣く")
        _known_for_30_days(committed_engine, card_id)
        due = review_card(
            card_id, ReviewAnswer(correct=True, duration_ms=5_000)
        ).card.due
        intervals[retention] = _days_from_now(due)

    assert intervals[0.75] > 2 * intervals[0.95]


def test_reviewing_another_users_card_is_refused(committed_engine, other_user):
    card_id = _new_card()

    with as_user(other_user), pytest.raises(HTTPException) as exc:
        review_card(card_id, ReviewAnswer(correct=True, duration_ms=1_000))

    assert exc.value.status_code == 404
    assert _reviews(committed_engine, card_id) == []


def test_reviewing_a_removed_card_is_refused(committed_engine):
    card_id = _new_card()
    suspend_card(card_id)

    with pytest.raises(HTTPException) as exc:
        review_card(card_id, ReviewAnswer(correct=True, duration_ms=1_000))

    assert exc.value.status_code == 409
    assert _reviews(committed_engine, card_id) == []


def test_a_review_cant_be_logged_against_another_users_song(
    committed_engine, other_user
):
    card_id = _new_card()
    with as_user(other_user):
        theirs = create_tokenized_document("君")

    with pytest.raises(HTTPException) as exc:
        review_card(
            card_id, ReviewAnswer(correct=True, duration_ms=1_000, document_id=theirs)
        )

    assert exc.value.status_code == 404
    assert _reviews(committed_engine, card_id) == []
    assert _row(committed_engine, card_id).last_review is None


# Pushing a card out


@pytest.mark.parametrize("months, days", [(1, 30), (3, 90), (6, 180)])
def test_pushing_a_card_out_makes_it_due_that_far_ahead(committed_engine, months, days):
    card_id = _new_card()

    card = push_out_card(card_id, PushOut(months=months))

    assert _days_from_now(card.due) == pytest.approx(days, abs=0.01)
    row = _row(committed_engine, card_id)
    # The stability matches, so the next review grows from it rather than
    # from a new card's.
    assert (row.state, row.step, row.stability) == (2, None, days)
    assert row.difficulty is not None


def test_pushing_a_card_out_is_a_reschedule_not_a_review(committed_engine):
    card_id = _new_card()
    review_card(card_id, ReviewAnswer(correct=False, duration_ms=5_000))
    before = _reviews(committed_engine, card_id)
    difficulty = _row(committed_engine, card_id).difficulty

    push_out_card(card_id, PushOut(months=3))

    assert _reviews(committed_engine, card_id) == before
    # What the card had learned about how hard the word is is kept.
    assert _row(committed_engine, card_id).difficulty == difficulty


def test_a_card_pushed_out_grows_from_there_on_its_next_review(committed_engine):
    card_id = _new_card()
    push_out_card(card_id, PushOut(months=1))
    _set(
        committed_engine,
        card_id,
        due="now()",
        last_review="now() - interval '30 days'",
    )

    review_card(card_id, ReviewAnswer(correct=True, duration_ms=5_000))

    assert _row(committed_engine, card_id).stability > 30


def test_a_card_can_only_be_pushed_out_one_three_or_six_months():
    with pytest.raises(ValidationError):
        PushOut(months=2)


def test_pushing_out_another_users_card_is_refused(committed_engine, other_user):
    card_id = _new_card()

    with as_user(other_user), pytest.raises(HTTPException) as exc:
        push_out_card(card_id, PushOut(months=1))

    assert exc.value.status_code == 404
    assert _days_from_now(_row(committed_engine, card_id).due) < 1


# Removing a card


def test_a_removed_card_leaves_both_queues(committed_engine):
    document_id = create_tokenized_document("君")
    [card] = start_song_session(document_id).cards

    assert suspend_card(card.id).suspended

    assert start_song_session(document_id).cards == []
    assert get_all_songs_queue().cards == []


def test_a_removed_card_keeps_its_history_and_adding_the_word_restores_it(
    committed_engine,
):
    document_id = create_tokenized_document("君")
    [card] = start_song_session(document_id).cards
    review_card(card.id, ReviewAnswer(correct=True, duration_ms=5_000))
    stability = _row(committed_engine, card.id).stability
    suspend_card(card.id)

    restored = add_token_card(document_id, document_tokens(document_id, "君")[0].id)

    assert (restored.id, restored.suspended) == (card.id, False)
    assert _row(committed_engine, card.id).stability == stability
    assert len(_reviews(committed_engine, card.id)) == 1


def test_removing_another_users_card_is_refused(committed_engine, other_user):
    card_id = _new_card()

    with as_user(other_user), pytest.raises(HTTPException) as exc:
        suspend_card(card_id)

    assert exc.value.status_code == 404
    assert not _row(committed_engine, card_id).suspended


# The queues


def test_studying_a_song_enrolls_its_words_up_to_its_daily_limit(committed_engine):
    document_id = create_tokenized_document(SONG)
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=2))

    queue = start_song_session(document_id).cards

    assert _lookup_forms(queue) == SONG_WORDS[:2]
    assert all(card.first_seen_document_id == document_id for card in queue)


def test_studying_a_song_again_the_same_day_enrolls_no_more(committed_engine):
    document_id = create_tokenized_document(SONG)
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=2))
    start_song_session(document_id)

    assert _lookup_forms(start_song_session(document_id).cards) == SONG_WORDS[:2]


def test_the_limit_frees_up_as_the_day_passes(committed_engine):
    document_id = create_tokenized_document(SONG)
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=2))
    start_song_session(document_id)
    with committed_engine.begin() as conn:
        conn.execute(
            text("UPDATE study_cards SET created_at = now() - interval '25 hours'")
        )

    assert _lookup_forms(start_song_session(document_id).cards) == SONG_WORDS[:4]


def test_raising_the_limit_enrolls_the_difference(committed_engine):
    document_id = create_tokenized_document(SONG)
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=2))
    start_song_session(document_id)
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=3))

    assert _lookup_forms(start_song_session(document_id).cards) == SONG_WORDS[:3]


def test_a_limit_of_zero_enrolls_nothing(committed_engine):
    document_id = create_tokenized_document(SONG)
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=0))

    assert start_song_session(document_id).cards == []


def test_the_default_limit_is_ten_a_song(committed_engine):
    long_song = "歌う。笑う。泣く。眠る。探す。話す。愛。涙。目。光。春。夏"
    document_id = create_tokenized_document(long_song)

    assert len(start_song_session(document_id).cards) == 10


def test_each_song_has_its_own_limit(committed_engine):
    first = create_tokenized_document("君を呼ぶ。")
    second = create_tokenized_document("泣く。話す。")
    save_song_study_settings(first, SongStudySettings(new_cards_per_day=1))

    assert len(start_song_session(first).cards) == 1
    assert len(start_song_session(second).cards) > 1


def test_a_songs_queue_holds_only_cards_for_its_words(committed_engine):
    first = create_tokenized_document("君を呼ぶ。")
    second = create_tokenized_document("泣く。話す。")
    start_song_session(first)

    assert _lookup_forms(start_song_session(second).cards) == ["泣く", "話す"]
    assert "泣く" not in _lookup_forms(start_song_session(first).cards)


def test_a_word_from_another_song_is_reviewed_in_this_one(committed_engine):
    first = create_tokenized_document("君を呼ぶ。")
    second = create_tokenized_document("君の声")
    start_song_session(first)

    assert "君" in _lookup_forms(start_song_session(second).cards)


def test_a_card_that_isnt_due_is_left_out_of_the_queue(committed_engine):
    document_id = create_tokenized_document("君")
    [card] = start_song_session(document_id).cards
    review_card(card.id, ReviewAnswer(correct=True, duration_ms=5_000))
    _set(committed_engine, card.id, due="now() + interval '1 day'")

    assert start_song_session(document_id).cards == []
    assert get_all_songs_queue().cards == []


def test_the_queue_is_ordered_by_due_date(committed_engine):
    document_id = create_tokenized_document("君を呼ぶ。")
    cards = start_song_session(document_id).cards
    by_form = {card.lookup_form: card.id for card in cards}
    _set(committed_engine, by_form["呼ぶ"], due="now() - interval '2 days'")
    _set(committed_engine, by_form["君"], due="now() - interval '1 day'")

    assert _lookup_forms(start_song_session(document_id).cards) == ["呼ぶ", "君"]


def test_a_word_added_by_hand_with_an_unreviewed_reading_is_in_its_songs_queue(
    committed_engine,
):
    document_id = create_tokenized_document("今日は")
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=0))
    add_token_card(document_id, document_tokens(document_id, "今日")[0].id)

    assert _lookup_forms(start_song_session(document_id).cards) == ["今日"]


def test_the_all_songs_queue_reaches_a_card_no_song_has_any_more(committed_engine):
    document_id = create_tokenized_document("君")
    [card] = start_song_session(document_id).cards
    with committed_engine.begin() as conn:
        conn.execute(text("DELETE FROM tokens"))

    assert start_song_session(document_id).cards == []
    assert [c.id for c in get_all_songs_queue().cards] == [card.id]


def test_the_all_songs_queue_holds_every_songs_due_cards(committed_engine):
    first = create_tokenized_document("君を呼ぶ。")
    second = create_tokenized_document("泣く。話す。")
    start_song_session(first)
    start_song_session(second)

    assert set(_lookup_forms(get_all_songs_queue().cards)) == {
        "君",
        "呼ぶ",
        "泣く",
        "話す",
    }


def test_each_user_has_their_own_queue(committed_engine, other_user):
    _new_card()

    with as_user(other_user):
        assert get_all_songs_queue().cards == []


# Settings


def test_the_settings_default_to_ninety_percent_and_ten_new_cards(committed_engine):
    document_id = create_tokenized_document("君")

    assert get_study_settings().desired_retention == 0.90
    assert get_song_study_settings(document_id).new_cards_per_day == 10


def test_saved_settings_are_read_back(committed_engine):
    document_id = create_tokenized_document("君")

    save_study_settings(StudySettings(desired_retention=0.85))
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=4))

    assert get_study_settings().desired_retention == 0.85
    assert get_song_study_settings(document_id).new_cards_per_day == 4


@pytest.mark.parametrize("retention", [0.74, 0.96, 1.0])
def test_a_desired_retention_outside_the_offered_range_is_refused(retention):
    with pytest.raises(ValidationError):
        StudySettings(desired_retention=retention)


def test_a_negative_new_card_limit_is_refused():
    with pytest.raises(ValidationError):
        SongStudySettings(new_cards_per_day=-1)


def test_retention_is_each_users_own(committed_engine, other_user):
    save_study_settings(StudySettings(desired_retention=0.8))

    with as_user(other_user):
        assert get_study_settings().desired_retention == 0.90


def test_changing_retention_leaves_due_dates_alone(committed_engine):
    card_id = _new_card()
    review_card(card_id, ReviewAnswer(correct=True, duration_ms=5_000))
    due = _row(committed_engine, card_id).due

    save_study_settings(StudySettings(desired_retention=0.75))

    assert _row(committed_engine, card_id).due == due


def test_overlapping_session_starts_both_get_every_card(committed_engine, monkeypatch):
    document_id = create_tokenized_document("君を呼ぶ。")
    second_began = threading.Event()
    first_enrolled = threading.Event()
    release_first = threading.Event()
    second_may_start = threading.Event()
    enroll = study.song_card_keys
    sessions = []

    def enroll_then_hold(*args):
        keys = enroll(*args)
        if not sessions:
            sessions.append("first")
            first_enrolled.set()
            release_first.wait(timeout=30)
        return keys

    monkeypatch.setattr("app.study.song_card_keys", enroll_then_hold)

    def first_session():
        with committed_engine.begin() as conn:
            return study.song_queue(conn, TEST_USER_ID, document_id)

    def second_session():
        with committed_engine.begin() as conn:
            # Fixes this transaction's now() before the first one starts.
            conn.execute(text("SELECT 1"))
            second_began.set()
            second_may_start.wait(timeout=30)
            return study.song_queue(conn, TEST_USER_ID, document_id)

    try:
        second = BackgroundCall(second_session)
        assert second_began.wait(timeout=30)
        first = BackgroundCall(first_session)
        assert first_enrolled.wait(timeout=30)
        second_may_start.set()
        wait_for_lock_wait()
    finally:
        release_first.set()
        second_may_start.set()

    first_cards = [row.id for row, _ in first.outcome().cards]
    second_cards = [row.id for row, _ in second.outcome().cards]
    assert first_cards
    assert second_cards == first_cards


def test_overlapping_session_starts_enroll_within_the_limit(
    committed_engine, monkeypatch
):
    document_id = create_tokenized_document("君を呼ぶ。")
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=1))
    first_enrolled = threading.Event()
    release_first = threading.Event()
    enroll = study.song_card_keys
    sessions = []

    def enroll_then_hold(*args):
        keys = enroll(*args)
        if not sessions:
            sessions.append("first")
            first_enrolled.set()
            release_first.wait(timeout=30)
        return keys

    monkeypatch.setattr("app.study.song_card_keys", enroll_then_hold)

    def session():
        with committed_engine.begin() as conn:
            return study.song_queue(conn, TEST_USER_ID, document_id)

    try:
        first = BackgroundCall(session)
        assert first_enrolled.wait(timeout=30)
        second = BackgroundCall(session)
        wait_for_lock_wait()
    finally:
        release_first.set()
    first.outcome()
    second.outcome()

    with committed_engine.connect() as conn:
        enrolled = conn.execute(
            text("SELECT count(*) FROM study_cards WHERE first_seen_document_id = :id"),
            {"id": document_id},
        ).scalar_one()
    assert enrolled == 1
