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
- `background_jobs`: processing jobs run on their own threads, as deployed.
  Otherwise a job runs inline (see `inline_jobs`), so the request that
  starts one returns once it's done.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

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


class _InlineExecutor:
    """Runs each job as it's submitted, keeping its outcome in the future
    returned, as a pool's thread would."""

    def submit(self, fn, *args) -> Future:
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:  # noqa: BLE001
            # Deliberately anything a job raises: a pool's future holds it
            # the same way, for the job's done callback to log.
            future.set_exception(exc)
        return future


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch):
    monkeypatch.setattr("app.processing._executor", _InlineExecutor())


@pytest.fixture
def background_jobs(committed_engine, monkeypatch):
    """A pool of the test's own, finished before committed_engine empties
    the tables a job writes to."""
    executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr("app.processing._executor", executor)
    yield executor
    executor.shutdown(wait=True)
