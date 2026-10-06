"""Song readiness and the run-through: what a song's cards say about how much
of it the user knows."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.main import SongStudySettings
from tests.support import (
    create_tokenized_document,
    get_run_through,
    get_song_readiness,
    list_documents,
    save_song_study_settings,
    start_song_session,
    suspend_card,
)

# 聞こえる is sung twice and the other four words once each, so six occurrences.
SONG = "君を呼ぶ。聞こえてる。聞こえた。"


def _set(engine, lookup_form: str, **columns) -> int:
    """Set columns of the card for `lookup_form`, each value SQL, and return
    its id."""
    assignments = ", ".join(f"{name} = {value}" for name, value in columns.items())
    with engine.begin() as conn:
        return conn.execute(
            text(
                f"UPDATE study_cards SET {assignments} "
                "WHERE lookup_form = :form RETURNING id"
            ),
            {"form": lookup_form},
        ).scalar_one()


def _recalled_now(engine, lookup_form: str) -> int:
    return _set(
        engine,
        lookup_form,
        state=2,
        step="NULL",
        stability=30,
        difficulty=5,
        last_review="now()",
        due="now() + interval '30 days'",
    )


def test_a_song_with_no_cards_is_not_ready_at_all(committed_engine):
    document_id = create_tokenized_document(SONG)

    readiness = get_song_readiness(document_id)

    assert readiness.readiness == 0
    assert (readiness.words, readiness.enrolled) == (5, 0)


def test_enrolled_words_never_reviewed_count_as_zero(committed_engine):
    document_id = create_tokenized_document(SONG)
    start_song_session(document_id)

    readiness = get_song_readiness(document_id)

    assert readiness.readiness == 0
    assert (readiness.words, readiness.enrolled) == (5, 5)


def test_readiness_is_weighted_by_how_often_a_word_is_sung(committed_engine):
    document_id = create_tokenized_document(SONG)
    start_song_session(document_id)
    _recalled_now(committed_engine, "聞こえる")

    # 聞こえる twice of six occurrences, recalled for certain.
    assert get_song_readiness(document_id).readiness == pytest.approx(2 / 6)


def test_words_without_a_card_pull_readiness_down(committed_engine):
    document_id = create_tokenized_document(SONG)
    save_song_study_settings(document_id, SongStudySettings(new_cards_per_day=1))
    start_song_session(document_id)
    _recalled_now(committed_engine, "聞こえる")

    readiness = get_song_readiness(document_id)

    # Only the card for the most sung word exists, so the rest count as zero
    # rather than being left out of the mean.
    assert (readiness.words, readiness.enrolled) == (5, 1)
    assert readiness.readiness == pytest.approx(2 / 6)


def test_a_removed_card_is_no_longer_part_of_the_song(committed_engine):
    document_id = create_tokenized_document(SONG)
    start_song_session(document_id)
    suspend_card(_recalled_now(committed_engine, "君"))

    readiness = get_song_readiness(document_id)

    assert (readiness.words, readiness.enrolled) == (4, 4)


def test_readiness_decays_as_time_passes(committed_engine):
    document_id = create_tokenized_document(SONG)
    start_song_session(document_id)
    _set(
        committed_engine,
        "君",
        state=2,
        step="NULL",
        stability=30,
        difficulty=5,
        last_review="now() - interval '30 days'",
        due="now()",
    )

    readiness = get_song_readiness(document_id)

    # 90% is what a stability of 30 days means after 30 days, over six
    # occurrences of which 君 has one.
    assert readiness.readiness == pytest.approx(0.9 / 6, abs=1e-3)
    # The other four cards are new, so due too.
    assert (readiness.mature, readiness.due) == (1, 5)


def test_a_card_is_mature_at_21_days_of_stability_and_due_once_its_date_comes(
    committed_engine,
):
    document_id = create_tokenized_document(SONG)
    start_song_session(document_id)
    _recalled_now(committed_engine, "君")
    _set(committed_engine, "呼ぶ", stability=20, state=2, last_review="now()")

    readiness = get_song_readiness(document_id)

    # 君 is mature, 呼ぶ isn't yet, and every other card is new and due now.
    assert readiness.mature == 1
    assert readiness.due == 4


def test_the_documents_list_shows_each_songs_readiness(committed_engine):
    document_id = create_tokenized_document(SONG)
    start_song_session(document_id)
    _recalled_now(committed_engine, "聞こえる")

    page = list_documents(page=1, page_size=20, sort_by="id", sort_dir="asc")

    [item] = [item for item in page.items if item.id == document_id]
    assert item.readiness.readiness == pytest.approx(2 / 6)
    assert item.readiness.words == 5


def test_the_documents_list_gives_each_song_only_its_own_words(committed_engine):
    first = create_tokenized_document(SONG)
    start_song_session(first)
    _recalled_now(committed_engine, "聞こえる")
    # Shares 君 and 聞こえる with the first song, which gave them cards, and
    # has one word of its own, 咲く, with no card.
    second = create_tokenized_document("君が聞こえる。花が咲く。")

    page = list_documents(page=1, page_size=20, sort_by="id", sort_dir="asc")

    listed = {item.id: item.readiness for item in page.items}
    for document_id in [first, second]:
        alone = get_song_readiness(document_id)
        assert listed[document_id].readiness == pytest.approx(alone.readiness)
        assert (
            listed[document_id].words,
            listed[document_id].enrolled,
            listed[document_id].mature,
            listed[document_id].due,
        ) == (alone.words, alone.enrolled, alone.mature, alone.due)
    assert (listed[second].words, listed[second].enrolled) == (3, 2)
    assert listed[second].readiness == pytest.approx(1 / 3)


def test_the_documents_list_sorts_by_readiness_before_cutting_a_page(
    committed_engine,
):
    ready = create_tokenized_document(SONG)
    start_song_session(ready)
    _recalled_now(committed_engine, "聞こえる")
    create_tokenized_document("花が咲く。")

    least_first = list_documents(
        page=1, page_size=1, sort_by="readiness", sort_dir="asc"
    )
    most_first = list_documents(
        page=1, page_size=1, sort_by="readiness", sort_dir="desc"
    )

    assert [item.id for item in most_first.items] == [ready]
    assert most_first.total == least_first.total
    assert least_first.items[0].readiness.readiness == 0


def test_a_run_through_pauses_on_lines_with_fading_words_weakest_first(
    committed_engine,
):
    document_id = create_tokenized_document("君を呼ぶ。\n聞こえてる。\nてる。")
    start_song_session(document_id)
    for form in ["君", "てる"]:
        _recalled_now(committed_engine, form)
    # Fading: recalled a month ago on a short stability.
    for form, stability in [("呼ぶ", 5), ("聞こえる", 1)]:
        _set(
            committed_engine,
            form,
            state=2,
            step="NULL",
            stability=stability,
            difficulty=5,
            last_review="now() - interval '30 days'",
            due="now() - interval '20 days'",
        )

    run = get_run_through(document_id)

    assert [line.text for line in run.lines] == ["君を呼ぶ。", "聞こえてる。", "てる。"]
    assert [[w.lookup_form for w in line.weak] for line in run.lines][:2] == [
        ["呼ぶ"],
        ["聞こえる"],
    ]
    [word] = run.lines[1].weak
    assert word.retrievability < 0.9
    assert word.meaning is not None and word.meaning.senses


def test_a_run_through_changes_nothing(committed_engine):
    document_id = create_tokenized_document(SONG)
    start_song_session(document_id)

    def snapshot():
        with committed_engine.connect() as conn:
            return conn.execute(
                text("SELECT id, due, state, last_review FROM study_cards ORDER BY id")
            ).all(), conn.execute(
                text("SELECT count(*) FROM study_reviews")
            ).scalar_one()

    before = snapshot()
    get_run_through(document_id)
    assert snapshot() == before
