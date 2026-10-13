"""Tests for the document tokens routes and the processing job behind
them, using public-domain text (tests/fixtures/kumo_no_ito.py) and short
test sentences. The routes commit their own transactions, so these use
`committed_engine`.
"""

from __future__ import annotations

import threading
from typing import NamedTuple

from alembic import command
from sqlalchemy import text

from app import processing
from app.glosses import is_glossable
from app.main import PROCESSING_FAILED, DocumentCreate, DocumentTextUpdate
from app.processing import (
    LEASE,
    _release,
    process_document,
    write_processed_document,
)
from app.tokenization import tokenize_document
from tests.fixtures.kumo_no_ito import FIRST_SENTENCE, SECOND_SENTENCE, TEXT, TITLE
from tests.support import (
    BackgroundCall,
    alembic_config,
    clear_gloss_links,
    create_document,
    fetch_document_tokens,
    get_document_tokens,
    pick_reading,
    process_document_tokens,
    round_trips,
    statements_sent,
    update_document_text,
)


class HeldProcessing(NamedTuple):
    # Each text a job processed, in order.
    texts: list[str]
    # Set as a job starts processing each held text.
    started: dict[str, threading.Event]
    # Set to let a job processing each held text go on.
    release: dict[str, threading.Event]

    def release_all(self) -> None:
        for event in self.release.values():
            event.set()


def hold_processing(monkeypatch, *held: str) -> HeldProcessing:
    """Record each text a job processes, holding a job processing any of
    `held` until the test releases it."""
    holds = HeldProcessing(
        [], {t: threading.Event() for t in held}, {t: threading.Event() for t in held}
    )

    def process(document_text):
        holds.texts.append(document_text)
        if document_text in holds.release:
            holds.started[document_text].set()
            holds.release[document_text].wait(timeout=30)
        return process_document(document_text)

    monkeypatch.setattr("app.processing.process_document", process)
    return holds


def test_first_processing_takes_a_fixed_number_of_round_trips(committed_engine):
    """A document's first processing costs one statement per kind of read
    and write, not one per token or per word, whether or not its glosses
    are already cached."""
    document_id = create_document(DocumentCreate(title=TITLE, text=TEXT)).id

    cold = statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    # Includes both requests (starting the job, after a read of its state,
    # then the poll that reads its tokens) with their ownership checks, the
    # job's claim and its release, create_phrase_conflicts' INSERT (this text
    # has phrase suggestions and predicate groups), one read of the cached
    # glosses its uncached predicate groups are built from, and one of the
    # lookups their pieces are shown from.
    assert round_trips(cold) == 15
    assert round_trips(cold, "INSERT INTO gloss_lookups") == 1

    # Changing the text deletes the tokens but keeps the gloss cache, so the
    # next request is a first processing where every gloss is already cached.
    update_document_text(document_id, DocumentTextUpdate(text=FIRST_SENTENCE))
    update_document_text(document_id, DocumentTextUpdate(text=TEXT))
    warm = statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    assert round_trips(warm) == 13
    assert round_trips(warm, "INSERT INTO gloss_lookups") == 0

    viewed = statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    assert round_trips(viewed) == 4


def test_a_dropped_piece_lookup_is_cached_again_by_the_first_view(committed_engine):
    """A composite gloss's piece whose lookup row was deleted, with no token
    linked to it, is looked up and kept by the next view, not looked up again
    on every one after."""
    document_id = create_document(DocumentCreate(title=TITLE, text=TEXT)).id
    get_document_tokens(document_id)
    with committed_engine.begin() as conn:
        dropped = conn.execute(
            text(
                """
                DELETE FROM gloss_lookups
                WHERE id NOT IN (
                    SELECT gloss_lookup_id FROM tokens
                    WHERE gloss_lookup_id IS NOT NULL
                )
                """
            )
        ).rowcount
    assert dropped > 0

    repaired = statements_sent(
        committed_engine, lambda: get_document_tokens(document_id)
    )
    assert round_trips(repaired, "INSERT INTO gloss_lookups") == 1

    viewed = statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    assert round_trips(viewed, "INSERT INTO gloss_lookups") == 0
    assert round_trips(viewed) == 4


def test_a_dropped_piece_lookup_alone_does_not_relink_glosses(
    committed_engine, monkeypatch
):
    """With every token linked, only the dropped lookup is repaired."""
    document_id = create_document(DocumentCreate(title=TITLE, text=TEXT)).id
    get_document_tokens(document_id)
    with committed_engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM gloss_lookups
                WHERE id NOT IN (
                    SELECT gloss_lookup_id FROM tokens
                    WHERE gloss_lookup_id IS NOT NULL
                )
                """
            )
        )

    def fail(*args):
        raise AssertionError("repair_gloss_links ran with every token linked")

    monkeypatch.setattr("app.main.repair_gloss_links", fail)
    get_document_tokens(document_id)


def test_requests_while_processing_start_no_second_job(background_jobs, monkeypatch):
    """A reload, another tab and the page's own polling, all while a job is
    processing the document, wait for that job rather than starting their
    own."""
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    held = hold_processing(monkeypatch, FIRST_SENTENCE)

    try:
        assert process_document_tokens(document_id).status == "processing"
        assert held.started[FIRST_SENTENCE].wait(timeout=30)
        assert process_document_tokens(document_id).status == "processing"
        assert fetch_document_tokens(document_id).status == "processing"
    finally:
        held.release_all()

    assert get_document_tokens(document_id)
    assert held.texts == [FIRST_SENTENCE]


def test_a_request_during_the_jobs_write_gets_its_tokens(background_jobs, monkeypatch):
    """A poll while the job's write is uncommitted reports processing
    without waiting on it, and the next poll gets the committed tokens."""
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id

    # Holds the job after it writes its tokens but before it commits, so
    # the request arrives while they're uncommitted.
    tokens_written = threading.Event()
    release = threading.Event()

    def write_then_wait(conn, document_id, processed):
        write_processed_document(conn, document_id, processed)
        tokens_written.set()
        release.wait(timeout=30)

    monkeypatch.setattr("app.processing.write_processed_document", write_then_wait)

    try:
        assert process_document_tokens(document_id).status == "processing"
        assert tokens_written.wait(timeout=30)
        assert fetch_document_tokens(document_id).status == "processing"
    finally:
        release.set()

    assert [t.id for t in get_document_tokens(document_id)]


def test_requests_that_both_read_before_claiming_claim_once(
    background_jobs, monkeypatch
):
    """Two requests that both find the document unclaimed before claiming it
    start one job between them."""
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    held = hold_processing(monkeypatch)

    # Holds each request after its first read until both have made it:
    # neither can go on to claim the document first, so the first two calls
    # are those reads.
    both_read = threading.Barrier(2, timeout=30)
    first_reads = iter(range(2))
    read_progress = processing._read_progress

    def read_progress_then_wait(conn, params):
        document = read_progress(conn, params)
        if next(first_reads, None) is not None:
            both_read.wait()
        return document

    monkeypatch.setattr("app.processing._read_progress", read_progress_then_wait)

    requests = [BackgroundCall(process_document_tokens, document_id) for _ in range(2)]
    assert [r.outcome().status for r in requests] == ["processing", "processing"]

    monkeypatch.setattr("app.processing._read_progress", read_progress)
    assert get_document_tokens(document_id)
    assert held.texts == [FIRST_SENTENCE]


def test_text_edited_mid_processing_gets_tokens_for_the_new_text(
    background_jobs, monkeypatch
):
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    held = hold_processing(monkeypatch, FIRST_SENTENCE, SECOND_SENTENCE)
    releases = []
    first_released = threading.Event()

    def recorded_release(conn, document_id, claimed_at, *, failed):
        released = _release(conn, document_id, claimed_at, failed=failed)
        releases.append(released)
        first_released.set()
        return released

    monkeypatch.setattr("app.processing._release", recorded_release)

    try:
        process_document_tokens(document_id)
        assert held.started[FIRST_SENTENCE].wait(timeout=30)
        # Would block until the job finished if it held a lock while
        # processing.
        update_document_text(document_id, DocumentTextUpdate(text=SECOND_SENTENCE))
        # The edit dropped the first job's claim, so the next poll starts a
        # job for the new text.
        assert fetch_document_tokens(document_id).status == "processing"
        assert held.started[SECOND_SENTENCE].wait(timeout=30)

        # The first job finishes while the second is still processing: its
        # claim is gone, so it writes nothing and leaves the second's alone.
        held.release[FIRST_SENTENCE].set()
        assert first_released.wait(timeout=30)
        assert releases == [False]
        assert fetch_document_tokens(document_id).status == "processing"
    finally:
        held.release_all()

    tokens = get_document_tokens(document_id)
    assert held.texts == [FIRST_SENTENCE, SECOND_SENTENCE]
    assert [t.surface for t in tokens] == [
        r.surface for r in tokenize_document(SECOND_SENTENCE)
    ]


def test_any_write_of_a_new_text_drops_its_tokens_and_claim(committed_engine):
    """Changing the text, by whatever statement, drops what processing
    derived from the old one: its tokens, their conflicts, and a job's claim
    or recorded failure."""
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    assert get_document_tokens(document_id)

    def processing_state():
        return conn.execute(
            text(
                """
                SELECT processing_started_at IS NOT NULL AS claimed,
                       processing_failed,
                       (SELECT count(*) FROM tokens WHERE document_id = :id) AS tokens,
                       (SELECT count(*) FROM conflicts c JOIN tokens t ON t.id = c.token_id
                        WHERE t.document_id = :id) AS conflicts
                FROM documents WHERE id = :id
                """
            ),
            {"id": document_id},
        ).one()

    with committed_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE documents
                SET processing_started_at = now(), processing_failed = TRUE
                WHERE id = :id
                """
            ),
            {"id": document_id},
        )
        state = processing_state()
        assert state.claimed and state.processing_failed and state.tokens
        assert state.conflicts

        conn.execute(
            text("UPDATE documents SET text = :text WHERE id = :id"),
            {"id": document_id, "text": SECOND_SENTENCE},
        )
        assert tuple(processing_state()) == (False, False, 0, 0)


def test_saving_the_same_text_keeps_its_tokens(committed_engine):
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    token_ids = [t.id for t in get_document_tokens(document_id)]

    update_document_text(document_id, DocumentTextUpdate(text=FIRST_SENTENCE))

    assert [t.id for t in fetch_document_tokens(document_id).tokens] == token_ids


def test_a_failed_job_is_reported_and_retried_only_when_asked(
    committed_engine, monkeypatch, caplog
):
    """Polling reports a failed job without starting another, which would
    fail again every time; starting processing, as a page load does, tries
    again."""
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    attempts = []

    def fail(document_text):
        attempts.append(document_text)
        raise RuntimeError("the tokenizer broke")

    monkeypatch.setattr("app.processing.process_document", fail)

    # Inline, the job has already failed by the time this returns.
    assert process_document_tokens(document_id).status == "processing"
    assert "the tokenizer broke" in caplog.text
    for _ in range(2):
        progress = fetch_document_tokens(document_id)
        assert (progress.status, progress.detail) == ("failed", PROCESSING_FAILED)
    assert len(attempts) == 1

    monkeypatch.setattr("app.processing.process_document", process_document)
    assert get_document_tokens(document_id)


def test_a_job_that_outlived_its_claim_is_started_over(committed_engine, monkeypatch):
    """A claim taken within its lease stands for a job still running; one
    older, for a job that died with its process, which a poll starts over."""
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    processed = hold_processing(monkeypatch)

    def claim_since(age):
        with committed_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE documents SET processing_started_at = now() - :age
                    WHERE id = :id
                    """
                ),
                {"id": document_id, "age": age},
            )

    claim_since(LEASE / 2)
    assert fetch_document_tokens(document_id).status == "processing"
    assert processed.texts == []

    claim_since(LEASE * 2)
    fetch_document_tokens(document_id)
    assert processed.texts == [FIRST_SENTENCE]
    assert fetch_document_tokens(document_id).status == "ready"


def test_a_job_that_writes_no_tokens_is_not_started_again(
    committed_engine, monkeypatch
):
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    with committed_engine.begin() as conn:
        conn.execute(
            text("UPDATE documents SET text = '' WHERE id = :id"), {"id": document_id}
        )
    processed = hold_processing(monkeypatch)

    assert get_document_tokens(document_id) == []
    progress = fetch_document_tokens(document_id)

    assert (progress.status, progress.tokens) == ("ready", [])
    assert processed.texts == [""]


def test_the_migration_marks_documents_with_tokens_as_processed(committed_engine):
    tokenized = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    get_document_tokens(tokenized)
    untouched = create_document(DocumentCreate(title=TITLE, text=SECOND_SENTENCE)).id

    config = alembic_config()
    command.downgrade(config, "0034")
    try:
        command.upgrade(config, "0035")
    finally:
        command.upgrade(config, "head")

    with committed_engine.connect() as conn:
        marked = dict(
            conn.execute(
                text("SELECT id, processed_at IS NOT NULL FROM documents")
            ).all()
        )
    assert marked == {tokenized: True, untouched: False}


def test_fetch_fills_in_missing_gloss_links_keeping_a_picked_reading(committed_engine):
    """Tokens with no gloss link (tokenized before gloss support existed) get
    one on the next fetch, and a token whose reading was picked from its
    conflicts keeps that reading's gloss rather than Sudachi's default."""
    document_id = create_document(
        DocumentCreate(title="test", text="今日は良い天気です。")
    ).id
    pick_reading(document_id, "今日", "こんにち")
    clear_gloss_links(document_id)

    tokens = get_document_tokens(document_id)

    assert all(
        t.gloss is not None
        for t in tokens
        if is_glossable(t.part_of_speech, bool(t.conflicts))
    )
    assert next(t for t in tokens if t.surface == "今日").gloss.reading == "こんにち"
