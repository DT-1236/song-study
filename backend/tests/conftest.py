"""Shared fixtures, all against the test database (see tests/support.py),
which is dropped and re-created from the migrations once per session.

- `db_conn`: a connection wrapped in a transaction that's rolled back at
  teardown, for tests that only need isolation from each other.
- `committed_engine`: for tests whose rows must really commit — to be seen
  from a second connection, or because the code under test runs its own
  transaction. Every table is emptied again at teardown.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

# Must be imported before anything that imports app.db.
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
        # Read from the catalog so a table added by a later migration is
        # emptied too. `users` keeps the default user the migrations seed.
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename NOT IN ('alembic_version', 'users')"
            )
        ).scalars().all()
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY"))
