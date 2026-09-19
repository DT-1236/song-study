"""Test database setup and shared helpers.

Database tests run against a dedicated test database named by
TEST_DATABASE_URL (see .env.example). Importing this module overrides
DATABASE_URL with it before anything imports app.db, so no test can reach
the app's own database — import it (conftest.py does) before anything that
imports app.db.
"""

from __future__ import annotations

import functools
import json
import os
import threading
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from app.env import load_env

BACKEND_DIR = Path(__file__).resolve().parent.parent

load_env()


def _test_database_url() -> str:
    """TEST_DATABASE_URL, refusing any database that could be the app's own
    — recreate_test_database drops and re-creates whatever this names."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set (see .env.example); tests never fall back to DATABASE_URL."
        )
    test_db = make_url(url).database
    app_url = os.environ.get("DATABASE_URL")
    if not test_db or not test_db.endswith("_test") or (app_url and make_url(app_url).database == test_db):
        raise RuntimeError(
            f"Refusing to use {test_db!r} as the test database: its name must end in '_test' "
            "and differ from DATABASE_URL's."
        )
    return url


# app.db builds its engine from DATABASE_URL at import time, and load_env
# never overrides a variable that's already set.
os.environ["DATABASE_URL"] = _test_database_url()

from app import main  # noqa: E402
from app.db import engine  # noqa: E402

# The user tests act as, inserted by recreate_test_database and kept by the
# `committed_engine` cleanup. Its id is far from any the tests' own inserts
# would hand out.
TEST_USER_ID = 1000


def recreate_test_database() -> None:
    """Drop and re-create the test database, then migrate it to head."""
    url = engine.url
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    # Pooled connections still point at the database that was just dropped.
    engine.dispose()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # Config values go through configparser interpolation, so % is escaped.
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
    command.upgrade(config, "head")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, name) VALUES (:id, 'test')"), {"id": TEST_USER_ID})


def statements_sent(engine, fn) -> list[tuple[str, int]]:
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


def round_trips(statements, prefix: str = "") -> int:
    """The round trips statements_sent recorded, for statements starting
    with `prefix`."""
    return sum(n for s, n in statements if s.startswith(prefix))


def wait_for_lock_wait(timeout: float = 10.0) -> None:
    """Return once some connection to the test database is waiting on a
    lock, so a concurrency test knows its second transaction has actually
    collided with the first rather than merely started."""
    deadline = time.monotonic() + timeout
    with engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting = conn.execute(
                text(
                    """
                    SELECT count(*) FROM pg_stat_activity
                    WHERE datname = current_database() AND wait_event_type = 'Lock'
                    """
                )
            ).scalar_one()
            # pg_stat_activity is snapshotted once per transaction.
            conn.commit()
            if waiting:
                return
            time.sleep(0.02)
    raise TimeoutError("no connection started waiting on a lock")


class BackgroundCall(threading.Thread):
    """Runs fn(*args) on its own thread; outcome() waits for it, then
    returns its result or re-raises its exception."""

    def __init__(self, fn, *args):
        # A daemon thread, unlike a ThreadPoolExecutor's (joined at exit),
        # can't keep pytest from exiting if it's stuck on a database lock.
        super().__init__(daemon=True)
        self._fn, self._args = fn, args
        self._result = self._error = None
        self.start()

    def run(self):
        try:
            self._result = self._fn(*self._args)
        except BaseException as exc:
            self._error = exc

    def outcome(self, timeout: float = 60.0):
        self.join(timeout)
        if self.is_alive():
            raise TimeoutError("background call did not finish")
        if self._error is not None:
            raise self._error
        return self._result


def make_token(conn, **overrides) -> int:
    """Insert a throwaway document + token row in the caller's transaction
    and return the token id."""
    document_id = conn.execute(
        text(
            """
            INSERT INTO documents (title, text, owner_id)
            VALUES ('test', 'test', :owner_id)
            RETURNING id
            """
        ),
        {"owner_id": TEST_USER_ID},
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


def document_tokens(document_id: int, surface: str) -> list:
    """The document's tokens with `surface`, in order, processing it first
    if it hasn't been."""
    return [t for t in get_document_tokens(document_id) if t.surface == surface]


def pick_reading(document_id: int, surface: str, reading: str) -> None:
    """Select `reading` among the options of the document's first token with
    `surface`."""
    from app.main import ConflictResolution

    token = document_tokens(document_id, surface)[0]
    option = next(c for c in token.conflicts if c.value["reading"] == reading)
    resolve_token_conflict(document_id, token.id, ConflictResolution(conflict_id=option.id))


def selected_reading(token) -> str:
    """The reading selected among a token's options."""
    return next(c for c in token.conflicts if c.selected).value["reading"]


def _as_test_user(route):
    """`route` with its `user_id` fixed to TEST_USER_ID."""

    @functools.wraps(route)
    def call(*args, **kwargs):
        return route(*args, user_id=TEST_USER_ID, **kwargs)

    return call


# The routes, acting as TEST_USER_ID: tests call them directly, with no
# request to log a user in. A test of another user's view calls the
# app.main route itself, with that `user_id`.
create_document = _as_test_user(main.create_document)
get_document = _as_test_user(main.get_document)
get_document_tokens = _as_test_user(main.get_document_tokens)
list_documents = _as_test_user(main.list_documents)
update_document_text = _as_test_user(main.update_document_text)
link_lrclib = _as_test_user(main.link_lrclib)
unlink_lrclib = _as_test_user(main.unlink_lrclib)
save_line_timings = _as_test_user(main.save_line_timings)
resolve_token_conflict = _as_test_user(main.resolve_token_conflict)
accept_phrase_suggestions_endpoint = _as_test_user(main.accept_phrase_suggestions_endpoint)
resolve_phrase_furigana_endpoint = _as_test_user(main.resolve_phrase_furigana_endpoint)
unmerge_phrase_tokens = _as_test_user(main.unmerge_phrase_tokens)
get_alternate_readings = _as_test_user(main.get_alternate_readings)
correct_token_reading = _as_test_user(main.correct_token_reading)
apply_tokens_reading = _as_test_user(main.apply_tokens_reading)
set_tokens_ignored = _as_test_user(main.set_tokens_ignored)
