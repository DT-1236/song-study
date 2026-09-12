"""Tests for GET /documents/{id}/tokens on a document's first processing,
using public-domain text (tests/fixtures/kumo_no_ito.py). The route commits
its own transaction, so these use `committed_engine`.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

import app.main
from app.main import DocumentTextUpdate, get_document_tokens, update_document_text
from tests.fixtures.kumo_no_ito import TEXT, TITLE
from tests.support import BackgroundCall, wait_for_lock_wait


def _create_document(engine) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text("INSERT INTO documents (title, text) VALUES (:title, :text) RETURNING id"),
            {"title": TITLE, "text": TEXT},
        ).scalar_one()


def _statements_sent(engine, fn) -> list[tuple[str, int]]:
    """Run fn and return (statement, round trips) for each statement it sent."""
    statements = []

    def record(conn, cursor, statement, params, context, executemany):
        # psycopg2 runs each row of an executemany as its own round trip.
        statements.append((statement.lstrip(), len(params) if executemany else 1))

    event.listen(engine, "before_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return statements


def _trips(statements, prefix: str = "") -> int:
    return sum(n for s, n in statements if s.startswith(prefix))


def test_first_processing_round_trips(committed_engine):
    """Pins how many DB round trips a document's first processing costs
    today, with an empty gloss cache and with a warm one, so batching its
    writes has a baseline to beat."""
    document_id = _create_document(committed_engine)

    cold = _statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    assert _trips(cold) == 1368
    assert _trips(cold, "SELECT id FROM gloss_lookups") == 209
    assert _trips(cold, "INSERT INTO gloss_lookups") == 172

    # Saving the text deletes the tokens but keeps the gloss cache, so the
    # next request is a first processing where every gloss is already cached.
    update_document_text(document_id, DocumentTextUpdate(text=TEXT))
    warm = _statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    assert _trips(warm) == 1196
    assert _trips(warm, "SELECT id FROM gloss_lookups") == 209
    assert _trips(warm, "INSERT INTO gloss_lookups") == 0


@pytest.mark.xfail(
    raises=IntegrityError,
    strict=True,
    reason=(
        "Both requests see no tokens and tokenize; the second blocks on the "
        "first's uncommitted (document_id, position) rows, then hits the "
        "unique constraint once the first commits."
    ),
)
def test_concurrent_first_requests_both_get_the_tokens(committed_engine, monkeypatch):
    document_id = _create_document(committed_engine)

    # Holds the first request between inserting its tokens and committing,
    # so the second is guaranteed to arrive while they're uncommitted.
    tokens_inserted = threading.Event()
    release = threading.Event()
    real_attach_glosses = app.main.attach_glosses

    def attach_glosses_once_released(conn, document_id):
        tokens_inserted.set()
        release.wait(timeout=30)
        real_attach_glosses(conn, document_id)

    monkeypatch.setattr(app.main, "attach_glosses", attach_glosses_once_released)

    try:
        first = BackgroundCall(get_document_tokens, document_id)
        assert tokens_inserted.wait(timeout=30)
        second = BackgroundCall(get_document_tokens, document_id)
        wait_for_lock_wait()
    finally:
        release.set()

    first_tokens = first.outcome()
    second_tokens = second.outcome()
    assert [t.id for t in second_tokens] == [t.id for t in first_tokens]
