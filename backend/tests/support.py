"""Test database setup and shared helpers.

Database tests run against a dedicated test database named by
TEST_DATABASE_URL (see .env.example). Importing this module overrides
DATABASE_URL with it before anything imports app.db, so no test can reach
the app's own database — import it (conftest.py does) before anything that
imports app.db. Under pytest-xdist, each worker gets a database of its own
named after TEST_DATABASE_URL's (`song_study_gw0_test` for worker gw0).

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
import re
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
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


def _refuse_unless_test_database(database: str | None, app_url: str | None) -> None:
    """Raise unless `database` is a name that can't be the app's own: one
    ending in `_test` and differing from `app_url`'s database."""
    if (
        not database
        or not database.endswith("_test")
        or (app_url and make_url(app_url).database == database)
    ):
        raise RuntimeError(
            f"Refusing to use {database!r} as the test database: its name must end in '_test' "
            "and differ from DATABASE_URL's."
        )


def _test_database_url(url: str | None, app_url: str | None, worker: str | None) -> str:
    """The database URL tests run against, given TEST_DATABASE_URL, the app's
    DATABASE_URL and the pytest-xdist worker id (None outside xdist): the
    test database itself, or for a worker a copy of its own, with the worker
    id before the `_test` suffix. Refuses any database that could be the
    app's own — recreate_test_database drops and re-creates whatever this
    names.
    """
    if not url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set (see .env.example); tests never fall back to DATABASE_URL."
        )
    parsed = make_url(url)
    # Checked before a worker's name is derived from it, so a base that's
    # refused can't gain a `_test` suffix it never had.
    _refuse_unless_test_database(parsed.database, app_url)
    if worker is None:
        return url
    if not re.fullmatch(r"gw\d+", worker):
        raise RuntimeError(f"Unexpected pytest-xdist worker id {worker!r}.")
    database = parsed.database.removesuffix("_test") + f"_{worker}_test"
    _refuse_unless_test_database(database, app_url)
    return parsed.set(database=database).render_as_string(hide_password=False)


# The worker id pytest-xdist gives this process, or None when the suite runs
# in a single process.
XDIST_WORKER = os.environ.get("PYTEST_XDIST_WORKER")

# xdist's workers inherit the environment of the process that started them,
# where DATABASE_URL has already been overridden below, so that process keeps
# the app's own for the workers' check. A worker without it compares against
# the inherited test database instead, which refuses that one too.
if XDIST_WORKER is None:
    _app_url = os.environ.get("DATABASE_URL")
    os.environ["SONG_STUDY_APP_DATABASE_URL"] = _app_url or ""
else:
    _app_url = os.environ.get(
        "SONG_STUDY_APP_DATABASE_URL", os.environ.get("DATABASE_URL")
    )

# app.db builds its engine from DATABASE_URL at import time, and load_env
# never overrides a variable that's already set.
os.environ["DATABASE_URL"] = _test_database_url(
    os.environ.get("TEST_DATABASE_URL"), _app_url, XDIST_WORKER
)

from app import main
from app.cards import CardKey
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


def _admin(statement: str) -> None:
    """Run `statement` on the test database's server, outside any database
    it could drop."""
    # Pooled connections still point at the database being dropped.
    engine.dispose()
    admin = create_engine(
        engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        conn.execute(text(statement))
    admin.dispose()


def drop_test_database() -> None:
    """Drop the test database, as a pytest-xdist worker does with its own at
    the end of a run: its name is only meaningful to that run."""
    _admin(f'DROP DATABASE IF EXISTS "{engine.url.database}" WITH (FORCE)')


def recreate_test_database() -> None:
    """Drop and re-create the test database, then migrate it to head."""
    drop_test_database()
    _admin(f'CREATE DATABASE "{engine.url.database}"')
    command.upgrade(alembic_config(), "head")
    with engine.begin() as conn:
        insert_test_user(conn)


def alembic_config() -> Config:
    """The Alembic config for migrating the test database."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    # Leaves the logging of the process it migrates in (the tests', or the
    # browser checks' server) as the app's would be, rather than disabling
    # every logger the app has already made.
    config.attributes["configure_logger"] = False
    # Config values go through configparser interpolation, so % is escaped.
    config.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


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


def get_document_tokens(document_id: int, timeout: float = 60.0) -> list:
    """The document's tokens, as a page gets them: starting it processing,
    then polling until that's done. Raises if processing failed."""
    progress = process_document_tokens(document_id)
    deadline = time.monotonic() + timeout
    while progress.status == "processing":
        if time.monotonic() > deadline:
            raise TimeoutError("processing did not finish")
        progress = fetch_document_tokens(document_id)
        # Only reached with jobs in the background: inline, the request that
        # started one has already finished it.
        if progress.status == "processing":
            time.sleep(0.05)
    if progress.status == "failed":
        raise RuntimeError(f"processing failed: {progress.detail}")
    return progress.tokens


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


def age_lrclib_check(document_id: int, age: timedelta) -> None:
    """Make the document's lyrics look last checked against LRCLIB `age`
    ago."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE documents SET lrclib_checked_at = now() - :age WHERE id = :id"
            ),
            {"id": document_id, "age": age},
        )


def age_lrclib_failure(document_id: int, age: timedelta) -> None:
    """Make the document's last failed check against LRCLIB look `age` ago."""
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE documents SET lrclib_failed_at = now() - :age WHERE id = :id"),
            {"id": document_id, "age": age},
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


# JMDict's entries for 合う; for 元 read もと, as "origin" and as "former";
# and for the words read うん: two written in kana, "yes" and "some", and 運.
TO_FIT = 1284430
ORIGIN, FORMER = 1260670, 2219590
YES, SOME, LUCK = 1001090, 2759530, 1172610


def pick_piece_word(document_id: int, token_ids: list[int], piece: int, idseq: int):
    """Pick JMDict entry `idseq` as the word `piece` of the gloss of each of
    the document's tokens `token_ids` is. Returns the tokens."""
    from app.main import PieceWordPick

    return pick_piece_word_endpoint(
        document_id, PieceWordPick(token_ids=token_ids, piece=piece, idseq=idseq)
    )


def word_key(lookup_form: str, reading: str, idseq: int | None = None) -> CardKey:
    """The key of the card for a word; with `idseq`, for one picked for a
    piece of katakana."""
    return CardKey("recognition", lookup_form, reading, idseq)


def user_cards(user_id: int = TEST_USER_ID) -> dict[CardKey, object]:
    """The user's card rows, removed or not, by key."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM study_cards WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).all()
    return {CardKey.of(row): row for row in rows}


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
            # Left out, as a client leaves out a parameter it has no value
            # for: sent, None would arrive as an empty string.
            elif value is not None:
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
fetch_document_tokens = _via_client(main.get_document_tokens)
process_document_tokens = _via_client(main.process_document_tokens)
list_documents = _via_client(main.list_documents)
update_document_text = _via_client(main.update_document_text)
link_lrclib = _via_client(main.link_lrclib)
unlink_lrclib = _via_client(main.unlink_lrclib)
refresh_lrclib = _via_client(main.refresh_lrclib)
save_line_timings = _via_client(main.save_line_timings)
resolve_token_conflict = _via_client(main.resolve_token_conflict)
accept_phrase_suggestions_endpoint = _via_client(
    main.accept_phrase_suggestions_endpoint
)
resolve_phrase_furigana_endpoint = _via_client(main.resolve_phrase_furigana_endpoint)
unmerge_phrase_tokens = _via_client(main.unmerge_phrase_tokens)
get_alternate_readings = _via_client(main.get_alternate_readings)
jmdict_search = _via_client(main.jmdict_search)
songs_search = _via_client(main.songs_search)
lrclib_search = _via_client(main.lrclib_search)
lrclib_track_lyrics = _via_client(main.lrclib_track_lyrics)
correct_token_reading = _via_client(main.correct_token_reading)
apply_tokens_reading = _via_client(main.apply_tokens_reading)
set_tokens_ignored = _via_client(main.set_tokens_ignored)
add_token_card = _via_client(main.add_token_card)
review_card = _via_client(main.review_card)
push_out_card = _via_client(main.push_out_card)
suspend_card = _via_client(main.suspend_card)
get_all_songs_queue = _via_client(main.get_all_songs_queue)
start_song_session = _via_client(main.start_song_session)
get_song_readiness = _via_client(main.get_song_readiness)
get_run_through = _via_client(main.get_run_through)
get_study_settings = _via_client(main.get_study_settings)
save_study_settings = _via_client(main.save_study_settings)
get_song_study_settings = _via_client(main.get_song_study_settings)
save_song_study_settings = _via_client(main.save_song_study_settings)
get_piece_words = _via_client(main.get_piece_words)
pick_piece_word_endpoint = _via_client(main.pick_piece_word_endpoint)
get_document_words = _via_client(main.get_document_words)
correct_card_reading = _via_client(main.correct_card_reading)
correct_card_word = _via_client(main.correct_card_word)


def accept_phrase_suggestion(document_id: int) -> list:
    """Accept the document's one phrase suggestion, returning the tokens it
    changed."""
    [suggestion] = [
        c.id
        for t in get_document_tokens(document_id)
        for c in t.conflicts
        if c.kind == "phrase"
    ]
    return accept_phrase_suggestions_endpoint(
        document_id, main.PhraseAcceptance(conflict_ids=[suggestion])
    )
