"""Shared fixtures.

Anything that touches the database uses `db_conn`, a connection wrapped in a
transaction that's always rolled back at teardown — so tests can freely
INSERT/UPDATE/DELETE without ever persisting anything, and without any risk
to the real documents already in this database (this project has no
separate test database; the dev one is used directly).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import text

from app.db import engine


@pytest.fixture
def db_conn():
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


def make_token(conn, **overrides) -> int:
    """Insert a throwaway document + token row (within the caller's
    transaction, so it never persists) and return the token id. Only
    `db_conn`-based tests should use this — it commits nothing itself, but
    the tables it writes to have foreign keys, so it needs a real
    transaction to work in, not a bare connection."""
    document_id = conn.execute(
        text(
            """
            INSERT INTO documents (title, text)
            VALUES ('test', 'test')
            RETURNING id
            """
        )
    ).scalar_one()

    defaults = {
        "document_id": document_id,
        "position": 0,
        "char_begin": 0,
        "char_end": 1,
        "surface": "test",
        "dictionary_form": "test",
        "normalized_form": "test",
        "reading_katakana": "test",
        "part_of_speech": ["名詞", "普通名詞", "一般", "*", "*", "*"],
        "is_oov": False,
        "furigana_spans": [{"start": 0, "end": 1, "text": "test", "reading": None}],
        "needs_review": False,
        "review_reason": None,
    }
    defaults.update(overrides)

    return conn.execute(
        text(
            """
            INSERT INTO tokens (
                document_id, position, char_begin, char_end, surface,
                dictionary_form, normalized_form, reading_katakana,
                part_of_speech, is_oov, furigana_spans, needs_review, review_reason
            ) VALUES (
                :document_id, :position, :char_begin, :char_end, :surface,
                :dictionary_form, :normalized_form, :reading_katakana,
                CAST(:part_of_speech AS JSONB), :is_oov,
                CAST(:furigana_spans AS JSONB), :needs_review, :review_reason
            )
            RETURNING id
            """
        ),
        {**defaults, "part_of_speech": json.dumps(defaults["part_of_speech"]), "furigana_spans": json.dumps(defaults["furigana_spans"])},
    ).scalar_one()
