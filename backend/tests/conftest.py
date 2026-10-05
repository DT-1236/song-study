"""Shared fixtures, all against the test database (see tests/support.py),
which is dropped and re-created from the migrations once per session.

- `db_conn`: a connection wrapped in a transaction that's rolled back at
  teardown, for tests that only need isolation from each other.
- `committed_engine`: for tests whose rows must really commit — to be seen
  from a second connection, or because the code under test runs its own
  transaction. Every table is emptied again at teardown, users included,
  and the test user is put back as new.
- `other_user`: the id of a second user, for tests that act as someone else
  (see `as_user` in tests/support.py).
"""

from __future__ import annotations

import pytest
from sqlalchemy import MetaData, text

# Must be imported before anything that imports app.db.
from tests.support import engine, insert_test_user, recreate_test_database


@pytest.fixture(scope="session")
def test_database():
    recreate_test_database()


@pytest.fixture(scope="session")
def empty_tables_sql(test_database) -> str:
    """One string of DELETEs emptying every table a test's rows can land in,
    each table before the ones its foreign keys point at."""
    # Reflected so a table added by a later migration is emptied too.
    metadata = MetaData()
    metadata.reflect(engine)
    # DELETE rather than TRUNCATE: on tables this small it's over ten times
    # faster, and this runs after every committing test.
    return "; ".join(
        f"DELETE FROM {table.name}"
        for table in reversed(metadata.sorted_tables)
        if table.name != "alembic_version"
    )


@pytest.fixture
def db_conn(test_database):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


@pytest.fixture
def committed_engine(empty_tables_sql):
    yield engine
    with engine.begin() as conn:
        conn.exec_driver_sql(empty_tables_sql)
        insert_test_user(conn)


@pytest.fixture
def other_user(committed_engine):
    with committed_engine.begin() as conn:
        return conn.execute(
            text("INSERT INTO users (name) VALUES ('other') RETURNING id")
        ).scalar_one()
