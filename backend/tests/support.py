"""Test database setup and shared helpers.

Database tests run against a dedicated test database named by
TEST_DATABASE_URL (see .env.example). Importing this module overrides
DATABASE_URL with it before anything imports app.db, so no test can reach
the app's own database — import it (conftest.py does) before anything that
imports app.db.

The routes it re-exports are called over HTTP through a TestClient, so a test
exercises the routing and the dependencies that a direct call to the route
function would skip. They keep the signatures and return types of the
functions they stand in for, and raise the HTTPException a failure carried.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter
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
    if (
        not test_db
        or not test_db.endswith("_test")
        or (app_url and make_url(app_url).database == test_db)
    ):
        raise RuntimeError(
            f"Refusing to use {test_db!r} as the test database: its name must end in '_test' "
            "and differ from DATABASE_URL's."
        )
    return url


# app.db builds its engine from DATABASE_URL at import time, and load_env
# never overrides a variable that's already set.
os.environ["DATABASE_URL"] = _test_database_url()

from app import main
from app.db import engine
from app.users import current_user_id

# The user tests act as, inserted by recreate_test_database and again by the
# `committed_engine` cleanup. Its id is far from any the tests' own inserts
# would hand out.
TEST_USER_ID = 1000


def insert_test_user(conn) -> None:
    """Insert the user tests act as, with every setting at its default."""
    conn.execute(
        text("INSERT INTO users (id, name) VALUES (:id, 'test')"),
        {"id": TEST_USER_ID},
    )


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
    config.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    command.upgrade(config, "head")
    with engine.begin() as conn:
        insert_test_user(conn)


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
        except BaseException as exc:  # noqa: BLE001
            # Deliberately everything: whatever the thread raised is re-raised
            # on the caller's thread by outcome(), and a KeyboardInterrupt or a
            # timeout that vanished here would hang the test instead.
            self._error = exc

    def outcome(self, timeout: float = 60.0):
        self.join(timeout)
        if self.is_alive():
            raise TimeoutError("background call did not finish")
        if self._error is not None:
            raise self._error
        return self._result


def make_document(conn) -> int:
    """Insert a throwaway document of the test user's in the caller's
    transaction and return its id."""
    return conn.execute(
        text(
            """
            INSERT INTO documents (title, text, owner_id)
            VALUES ('test', 'test', :owner_id)
            RETURNING id
            """
        ),
        {"owner_id": TEST_USER_ID},
    ).scalar_one()


def make_token(conn, **overrides) -> int:
    """Insert a token row in the caller's transaction and return its id. It
    goes in a throwaway document unless `document_id` is given."""
    defaults = {
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
    if "document_id" not in overrides:
        defaults["document_id"] = make_document(conn)

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
        {
            **defaults,
            "part_of_speech": json.dumps(defaults["part_of_speech"]),
            "furigana_spans": json.dumps(defaults["furigana_spans"]),
        },
    ).scalar_one()


def create_tokenized_document(text: str = "", title: str = "test") -> int:
    """The id of a new document of `text`, already tokenized."""
    from app.main import DocumentCreate

    document_id = create_document(DocumentCreate(title=title, text=text)).id
    get_document_tokens(document_id)
    return document_id


def document_tokens(document_id: int, surface: str) -> list:
    """The document's tokens with `surface`, in order, processing it first
    if it hasn't been."""
    return [t for t in get_document_tokens(document_id) if t.surface == surface]


def clear_gloss_links(document_id: int) -> None:
    """Unlink every token of the document from its gloss, as a migration
    clearing stale glosses leaves them."""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE tokens SET gloss_lookup_id = NULL WHERE document_id = :id"),
            {"id": document_id},
        )


def empty_gloss_cache() -> None:
    """Empty gloss_lookups, as migrations 0013-0015 do whenever gloss logic
    changes."""
    with engine.begin() as conn:
        conn.execute(text("UPDATE tokens SET gloss_lookup_id = NULL"))
        conn.execute(text("DELETE FROM gloss_lookups"))


def pick_reading(document_id: int, surface: str, reading: str) -> None:
    """Select `reading` among the options of the document's first token with
    `surface`."""
    from app.main import ConflictResolution

    token = document_tokens(document_id, surface)[0]
    option = next(c for c in token.conflicts if c.value["reading"] == reading)
    resolve_token_conflict(
        document_id, token.id, ConflictResolution(conflict_id=option.id)
    )


def selected_reading(token) -> str:
    """The reading selected among a token's options."""
    return next(c for c in token.conflicts if c.selected).value["reading"]


# None means no one is impersonated: the request's own session decides.
_acting_user: list[int | None] = [TEST_USER_ID]


def _acting_user_or_session(request: Request) -> int:
    user_id = _acting_user[-1]
    return current_user_id(request) if user_id is None else user_id


# Who the routes below act as. Overriding the dependency, rather than logging
# a user in over HTTP, keeps the Google flow out of every test.
main.app.dependency_overrides[current_user_id] = _acting_user_or_session

client = TestClient(main.app)


@contextmanager
def as_user(user_id: int):
    """Route calls inside the block act as `user_id` rather than
    TEST_USER_ID."""
    _acting_user.append(user_id)
    try:
        yield user_id
    finally:
        _acting_user.pop()


@contextmanager
def as_session_user():
    """Route calls inside the block act as whoever their request's session
    says, rather than as TEST_USER_ID."""
    _acting_user.append(None)
    try:
        yield
    finally:
        _acting_user.pop()


def api_routes(routes=None):
    """Every APIRoute the app serves. Including a router nests it rather
    than copying its routes, so the app's own list has to be walked."""
    for route in main.app.routes if routes is None else routes:
        if isinstance(route, APIRoute):
            yield route
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from api_routes(included.routes)


def _route_for(endpoint) -> APIRoute:
    for route in api_routes():
        if route.endpoint is endpoint:
            return route
    raise LookupError(f"{endpoint.__name__} is not registered as a route")


def _via_client(endpoint):
    """`endpoint` called over HTTP as the acting user, keeping its own
    signature and response model, so a test reads like a direct call but
    goes through the routing and the dependencies a direct call skips."""
    route = _route_for(endpoint)
    method = next(m for m in route.methods if m != "HEAD")
    signature = inspect.signature(endpoint)
    # `response_model` is what the route declares; None for a bare dict.
    adapter = TypeAdapter(route.response_model) if route.response_model else None

    @functools.wraps(endpoint)
    def call(*args, **kwargs):
        path_args, query, body = {}, {}, None
        for name, value in signature.bind_partial(*args, **kwargs).arguments.items():
            if name == "user_id":
                raise TypeError("act as another user with as_user(), not user_id=")
            if f"{{{name}}}" in route.path:
                path_args[name] = value
            elif isinstance(value, BaseModel):
                body = value.model_dump(mode="json")
            else:
                query[name] = value

        response = client.request(
            method, route.path.format(**path_args), params=query, json=body
        )
        if response.status_code >= 400:
            # So a test can assert on the failure the same way either side
            # of this harness: as the HTTPException the route raised.
            raise HTTPException(response.status_code, response.json().get("detail"))
        if not response.content:
            return None
        return adapter.validate_python(response.json()) if adapter else response.json()

    return call


# The routes, acting as TEST_USER_ID unless a test wraps the call in
# as_user(...).
create_document = _via_client(main.create_document)
get_document = _via_client(main.get_document)
get_document_tokens = _via_client(main.get_document_tokens)
list_documents = _via_client(main.list_documents)
update_document_text = _via_client(main.update_document_text)
link_lrclib = _via_client(main.link_lrclib)
unlink_lrclib = _via_client(main.unlink_lrclib)
save_line_timings = _via_client(main.save_line_timings)
resolve_token_conflict = _via_client(main.resolve_token_conflict)
accept_phrase_suggestions_endpoint = _via_client(
    main.accept_phrase_suggestions_endpoint
)
resolve_phrase_furigana_endpoint = _via_client(main.resolve_phrase_furigana_endpoint)
unmerge_phrase_tokens = _via_client(main.unmerge_phrase_tokens)
get_alternate_readings = _via_client(main.get_alternate_readings)
jmdict_search = _via_client(main.jmdict_search)
correct_token_reading = _via_client(main.correct_token_reading)
apply_tokens_reading = _via_client(main.apply_tokens_reading)
set_tokens_ignored = _via_client(main.set_tokens_ignored)
add_token_card = _via_client(main.add_token_card)
review_card = _via_client(main.review_card)
push_out_card = _via_client(main.push_out_card)
suspend_card = _via_client(main.suspend_card)
get_all_songs_queue = _via_client(main.get_all_songs_queue)
start_song_session = _via_client(main.start_song_session)
get_study_settings = _via_client(main.get_study_settings)
save_study_settings = _via_client(main.save_study_settings)
get_song_study_settings = _via_client(main.get_song_study_settings)
save_song_study_settings = _via_client(main.save_song_study_settings)
