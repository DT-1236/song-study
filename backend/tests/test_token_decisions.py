"""Tests for applying one reading or ignore decision to several of a
document's tokens at once. The routes commit their own transactions, so these
use `committed_engine`.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.main import (
    DocumentCreate,
    TokensIgnored,
    TokensReading,
)
from tests.support import (
    apply_tokens_reading,
    create_document,
    document_tokens,
    round_trips,
    selected_reading,
    set_tokens_ignored,
    statements_sent,
)

# Two instances each of 今日, a heteronym, and は, which offers no options.
TEXT = "今日は晴れ。今日は雨。"


def test_a_reading_is_picked_from_each_tokens_own_options(committed_engine):
    document_id = create_document(DocumentCreate(title="test", text=TEXT)).id
    todays = document_tokens(document_id, "今日")

    updated = apply_tokens_reading(
        document_id, TokensReading(token_ids=[t.id for t in todays], reading="こんにち")
    )

    assert [t.id for t in updated] == [t.id for t in todays]
    assert [selected_reading(t) for t in updated] == ["こんにち", "こんにち"]
    assert [t.gloss.reading for t in updated] == ["こんにち", "こんにち"]
    # Selected among the options each already had, not added as corrections.
    assert [len(t.conflicts) for t in updated] == [len(t.conflicts) for t in todays]


def test_a_reading_no_option_has_becomes_one_correction(committed_engine):
    document_id = create_document(DocumentCreate(title="test", text=TEXT)).id
    ids = [t.id for t in document_tokens(document_id, "は")]

    apply_tokens_reading(document_id, TokensReading(token_ids=ids, reading="わ"))
    updated = apply_tokens_reading(
        document_id, TokensReading(token_ids=ids, reading="わ")
    )

    assert [selected_reading(t) for t in updated] == ["わ", "わ"]
    # Sudachi's own reading, kept to return to, and the correction, which the
    # second request selected again rather than adding another.
    assert [len(t.conflicts) for t in updated] == [2, 2]


def test_ignoring_applies_to_every_given_token_and_can_be_undone(committed_engine):
    document_id = create_document(DocumentCreate(title="test", text=TEXT)).id
    ids = [t.id for t in document_tokens(document_id, "今日")]

    ignored = set_tokens_ignored(
        document_id, TokensIgnored(token_ids=ids, ignored=True)
    )
    restored = set_tokens_ignored(
        document_id, TokensIgnored(token_ids=ids, ignored=False)
    )

    assert [t.gloss_ignored for t in ignored] == [True, True]
    assert [t.gloss_ignored for t in restored] == [False, False]


def test_another_documents_token_is_refused_and_nothing_changes(committed_engine):
    document_id = create_document(DocumentCreate(title="test", text=TEXT)).id
    other_id = create_document(DocumentCreate(title="other", text=TEXT)).id
    ids = [t.id for t in document_tokens(document_id, "今日")] + [
        document_tokens(other_id, "今日")[0].id
    ]

    for decide in (
        lambda: apply_tokens_reading(
            document_id, TokensReading(token_ids=ids, reading="こんにち")
        ),
        lambda: set_tokens_ignored(
            document_id, TokensIgnored(token_ids=ids, ignored=True)
        ),
    ):
        with pytest.raises(HTTPException) as refused:
            decide()
        assert refused.value.status_code == 404

    todays = document_tokens(document_id, "今日")
    assert [selected_reading(t) for t in todays] == ["きょう", "きょう"]
    assert not any(t.gloss_ignored for t in todays)


def test_tokens_parsed_differently_are_refused_together(committed_engine):
    # 人 as a noun (ひと) and as a counter suffix (にん): the same surface,
    # but not the same word.
    document_id = create_document(
        DocumentCreate(title="test", text="人が来た。三人来た。")
    ).id
    people = document_tokens(document_id, "人")
    ids = [t.id for t in people]
    assert len({t.reading_katakana for t in people}) == 2

    for decide in (
        lambda: apply_tokens_reading(
            document_id, TokensReading(token_ids=ids, reading="ひと")
        ),
        lambda: set_tokens_ignored(
            document_id, TokensIgnored(token_ids=ids, ignored=True)
        ),
    ):
        with pytest.raises(HTTPException) as refused:
            decide()
        assert refused.value.status_code == 422

    assert [selected_reading(t) for t in document_tokens(document_id, "人")] == [
        selected_reading(t) for t in people
    ]


@pytest.mark.parametrize("reading", ["こんにち", "こんち"])
def test_deciding_for_more_tokens_takes_no_more_statements(committed_engine, reading):
    """Picking an offered option (こんにち) or adding a correction (こんち)
    costs the same statements for one token as for several."""
    documents = [
        create_document(DocumentCreate(title=f"{n}", text="今日は晴れ。" * n)).id
        for n in (1, 1, 3)
    ]
    counts = []
    for document_id in documents:
        ids = [t.id for t in document_tokens(document_id, "今日")]
        sent = statements_sent(
            committed_engine,
            lambda: apply_tokens_reading(
                document_id, TokensReading(token_ids=ids, reading=reading)
            ),
        )
        counts.append(round_trips(sent))

    # The first document's decision also caches the reading's gloss.
    assert counts[1] == counts[2]
