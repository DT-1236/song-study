"""Shared fixtures, all against the test database (see tests/support.py),
which is dropped and re-created from the migrations once per session.

- `db_conn`: a connection wrapped in a transaction that's rolled back at
  teardown, for tests that only need isolation from each other.
- `committed_engine`: for tests whose rows must really commit — to be seen
  from a second connection, or because the code under test runs its own
  transaction. Every table is emptied again at teardown.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import text

# Must be imported before anything from `app`.
from tests.support import engine, recreate_test_database


@pytest.fixture(scope="session")
def test_database():
    recreate_test_database()


@pytest.fixture
def db_conn(test_database):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


@pytest.fixture
def committed_engine(test_database):
    yield engine
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE conflicts, tokens, gloss_lookups, documents RESTART IDENTITY"))
