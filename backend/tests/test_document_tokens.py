"""Tests for GET /documents/{id}/tokens, using public-domain text
(tests/fixtures/kumo_no_ito.py) and short test sentences. The route commits
its own transactions, so these use `committed_engine`.
"""

from __future__ import annotations

import threading

from sqlalchemy import text

from app.glosses import is_glossable
from app.main import (
    DocumentCreate,
    DocumentTextUpdate,
    _process_document,
    _write_processed_document,
)
from app.tokenization import tokenize_document
from tests.fixtures.kumo_no_ito import FIRST_SENTENCE, SECOND_SENTENCE, TEXT, TITLE
from tests.support import (
    BackgroundCall,
    clear_gloss_links,
    create_document,
    get_document_tokens,
    pick_reading,
    round_trips,
    statements_sent,
    update_document_text,
    wait_for_lock_wait,
)


def test_first_processing_takes_a_fixed_number_of_round_trips(committed_engine):
    """A document's first processing costs one statement per kind of read
    and write, not one per token or per word, whether or not its glosses
    are already cached."""
    document_id = create_document(DocumentCreate(title=TITLE, text=TEXT)).id

    cold = statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    # Includes the ownership check, create_phrase_conflicts' INSERT (this text has phrase
    # suggestions and predicate groups), one read of the cached glosses
    # its uncached predicate groups are built from, and one of the lookups
    # their pieces are shown from.
    assert round_trips(cold) == 14
    assert round_trips(cold, "INSERT INTO gloss_lookups") == 1

    # Saving the text deletes the tokens but keeps the gloss cache, so the
    # next request is a first processing where every gloss is already cached.
    update_document_text(document_id, DocumentTextUpdate(text=TEXT))
    warm = statements_sent(committed_engine, lambda: get_document_tokens(document_id))
    assert round_trips(warm) == 12
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


def test_concurrent_first_requests_both_get_the_tokens(committed_engine, monkeypatch):
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id

    # Holds the first request after it writes its tokens but before it
    # commits, so the second arrives while they're uncommitted.
    tokens_written = threading.Event()
    release = threading.Event()

    def write_then_wait(conn, document_id, processed):
        _write_processed_document(conn, document_id, processed)
        tokens_written.set()
        release.wait(timeout=30)

    monkeypatch.setattr("app.main._write_processed_document", write_then_wait)

    try:
        first = BackgroundCall(get_document_tokens, document_id)
        assert tokens_written.wait(timeout=30)
        second = BackgroundCall(get_document_tokens, document_id)
        wait_for_lock_wait()
    finally:
        release.set()

    first_tokens = first.outcome()
    second_tokens = second.outcome()
    assert first_tokens
    assert [t.id for t in second_tokens] == [t.id for t in first_tokens]


def test_text_edited_mid_processing_gets_tokens_for_the_new_text(
    committed_engine, monkeypatch
):
    document_id = create_document(DocumentCreate(title=TITLE, text=FIRST_SENTENCE)).id
    texts_processed = []

    def process_then_edit(document_text):
        processed = _process_document(document_text)
        if not texts_processed:
            # Would block forever if the request held a lock while processing.
            update_document_text(document_id, DocumentTextUpdate(text=SECOND_SENTENCE))
        texts_processed.append(document_text)
        return processed

    monkeypatch.setattr("app.main._process_document", process_then_edit)

    tokens = get_document_tokens(document_id)

    assert texts_processed == [FIRST_SENTENCE, SECOND_SENTENCE]
    assert [t.surface for t in tokens] == [
        r.surface for r in tokenize_document(SECOND_SENTENCE)
    ]


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
