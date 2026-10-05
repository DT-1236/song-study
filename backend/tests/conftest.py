"""Shared fixtures, all against the test database (see tests/support.py),
which is dropped and re-created from the migrations once per session.

- `db_conn`: a connection wrapped in a transaction that's rolled back at
  teardown, for tests that only need isolation from each other.
- `committed_engine`: for tests whose rows must really commit — to be seen
  from a second connection, or because the code under test runs its own
  transaction. Every table is emptied again at teardown, and the test user's
  settings are put back.
- `other_user`: the id of a second user, for tests that act as someone else
  (see `as_user` in tests/support.py).
"""

from __future__ import annotations

from graphlib import TopologicalSorter

import pytest
from sqlalchemy import text

# Must be imported before anything that imports app.db.
from tests.support import TEST_USER_ID, engine, recreate_test_database


@pytest.fixture(scope="session")
def test_database():
    recreate_test_database()


@pytest.fixture(scope="session")
def tables_to_empty(test_database) -> list[str]:
    """Every table a test's rows can land in except `users`, which keeps the
    user tests act as, ordered so each comes before the tables its foreign
    keys point at."""
    with engine.connect() as conn:
        return _in_delete_order(conn)


def _in_delete_order(conn) -> list[str]:
    # Read from the catalog so a table added by a later migration is
    # emptied too.
    tables = (
        conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename NOT IN ('alembic_version', 'users')"
            )
        )
        .scalars()
        .all()
    )
    references = conn.execute(
        text(
            """
            SELECT conrelid::regclass::text AS child, confrelid::regclass::text AS parent
            FROM pg_constraint
            WHERE contype = 'f' AND connamespace = 'public'::regnamespace
            """
        )
    ).all()
    # Each table's predecessors are the tables referencing it.
    referenced_by = {table: set() for table in tables}
    for child, parent in references:
        if parent in referenced_by and child != parent:
            referenced_by[parent].add(child)
    return list(TopologicalSorter(referenced_by).static_order())


def _empty_tables(conn, tables: list[str]) -> None:
    # DELETE rather than TRUNCATE: on tables this small it's about twenty
    # times faster, and this runs after every committing test.
    for table in tables:
        conn.execute(text(f"DELETE FROM {table}"))


@pytest.fixture
def db_conn(test_database):
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


@pytest.fixture
def committed_engine(tables_to_empty):
    yield engine
    with engine.begin() as conn:
        _empty_tables(conn, tables_to_empty)
        conn.execute(
            text("UPDATE users SET desired_retention = DEFAULT WHERE id = :id"),
            {"id": TEST_USER_ID},
        )


@pytest.fixture
def other_user(committed_engine, tables_to_empty):
    with committed_engine.begin() as conn:
        user_id = conn.execute(
            text("INSERT INTO users (name) VALUES ('other') RETURNING id")
        ).scalar_one()
    yield user_id
    with committed_engine.begin() as conn:
        # Everything else is emptied by committed_engine, but only after
        # this runs, and the user's rows have to go first.
        _empty_tables(conn, tables_to_empty)
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
