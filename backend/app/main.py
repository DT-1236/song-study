import dataclasses
import json
import logging
import os
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal, NamedTuple

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware

from app import processing, study
from app.auth import APP_URL, session_secret
from app.auth import router as auth_router
from app.card_content import Line, Option, Queue, RunLine
from app.cards import CardKind, NotStudyable, document_words, enroll_token
from app.conflicts import (
    IS_ACCEPTED_PHRASE_SQL,
    ConflictNotFound,
    TokenNotFound,
    TokensNotGroupable,
    WordNotOffered,
    accept_phrase_suggestions,
    correct_reading,
    lock_token_group,
    pick_piece_word,
    piece_word_options,
    repair_gloss_links,
    resolve_conflict,
    resolve_phrase_furigana,
    select_reading,
    token_reading_options,
    unmerge_phrase,
)
from app.db import DOCUMENT_COLUMNS, engine, json_param, owned_document_row
from app.glosses import (
    KATAKANA_GLOSS_COLUMNS,
    is_glossable,
    is_probably_english,
    picked_katakana_gloss,
    piece_lookups,
    rank_senses,
    search_jmdict,
    shown_pieces,
)
from app.kanji import MAX_DECK_WORDS, CardKanji, KanjiEntry
from app.lrclib import (
    LrclibCandidate,
    LrclibError,
    LrclibLyrics,
    LrclibRateLimited,
    LrclibUnavailable,
    fetch_lyrics,
    normalize_lrclib_uri,
    search_tracks,
)
from app.sanitize import sanitize_text
from app.tokenization import (
    dictionary_form_note,
    mixed_reading,
)
from app.users import CurrentUser, OwnedDocument
from app.youtube_music import Song, YouTubeMusicUnavailable, search_songs


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Configures the root logger when the server starts, so importing the
    app (tests, scripts) leaves logging alone.
    """
    # Uvicorn only configures its own loggers, so without this the app's INFO
    # logs (LRCLIB requests, for one) never show.
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    yield


app = FastAPI(docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)

# The API is served under /api on the app's own origin, so there's no CORS.
# Its cookie is Secure exactly when the app is served over https.
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    same_site="lax",
    https_only=APP_URL.startswith("https://"),
)


@app.exception_handler(study.DocumentNotFound)
def document_not_found(request: Request, exc: study.DocumentNotFound) -> JSONResponse:
    """A 404 for a study call naming a document that isn't the user's: one
    from a request body, or one deleted after the route's own check."""
    return JSONResponse(status_code=404, content={"detail": "Document not found."})


@app.exception_handler(study.CardNotFound)
def card_not_found(request: Request, exc: study.CardNotFound) -> JSONResponse:
    """A 404 for a card that isn't the user's."""
    return JSONResponse(status_code=404, content={"detail": "Card not found."})


@app.exception_handler(study.CardSuspended)
def card_suspended(request: Request, exc: study.CardSuspended) -> JSONResponse:
    """A 409 for answering a card the user removed from study."""
    return JSONResponse(
        status_code=409,
        content={"detail": "This card was removed from your list."},
    )


@app.exception_handler(NotStudyable)
def not_studyable(request: Request, exc: NotStudyable) -> JSONResponse:
    """A 422 for a token that isn't part of a word with a dictionary entry."""
    return JSONResponse(
        status_code=422,
        content={"detail": "This isn't a word with a dictionary entry to study."},
    )


@app.exception_handler(TokenNotFound)
def token_not_found(request: Request, exc: TokenNotFound) -> JSONResponse:
    """A 404 for a token that isn't in the document the route names."""
    return JSONResponse(status_code=404, content={"detail": "Token not found."})


@app.exception_handler(ConflictNotFound)
def conflict_not_found(request: Request, exc: ConflictNotFound) -> JSONResponse:
    """A 404 for a conflict option that isn't in the document the route names."""
    return JSONResponse(
        status_code=404, content={"detail": "Conflict option not found."}
    )


@app.exception_handler(study.ReviewNotFound)
def review_not_found(request: Request, exc: study.ReviewNotFound) -> JSONResponse:
    """A 404 for undoing a review that isn't one of the card's."""
    return JSONResponse(status_code=404, content={"detail": "Review not found."})


@app.exception_handler(study.NotCorrectable)
def not_correctable(request: Request, exc: study.NotCorrectable) -> JSONResponse:
    """A 422 for a correction a card's token doesn't take."""
    return JSONResponse(
        status_code=422,
        content={"detail": "This word can't be corrected that way."},
    )


@app.exception_handler(WordNotOffered)
def word_not_offered(request: Request, exc: WordNotOffered) -> JSONResponse:
    """A 422 for picking a word that a piece of katakana can't be."""
    return JSONResponse(
        status_code=422,
        content={"detail": "That isn't one of the words this can be."},
    )


@app.exception_handler(TokensNotGroupable)
def tokens_not_groupable(request: Request, exc: TokensNotGroupable) -> JSONResponse:
    """A 422 for tokens lock_token_group refused to decide for together."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Those tokens aren't one word read and parsed the same way, so they can't be decided for together."
        },
    )


# How much longer than LRCLIB's own wait the client is told to hold off, so
# its next request lands after the limit has surely lifted.
RATE_LIMIT_CLIENT_FACTOR = 1.5


@app.exception_handler(LrclibRateLimited)
def lrclib_rate_limited(request: Request, exc: LrclibRateLimited) -> JSONResponse:
    """A 429 for LRCLIB's rate limit, saying how long the client should
    stop sending it searches."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": str(exc),
            "retry_after_seconds": exc.retry_after_seconds * RATE_LIMIT_CLIENT_FACTOR,
        },
    )


class LrclibRefreshTooSoon(Exception):
    """A manual refresh from LRCLIB asked for before the last check of the
    document's lyrics is `LRCLIB_REFRESH_COOLDOWN` old."""

    def __init__(self, retry_after_seconds: float):
        self.retry_after_seconds = retry_after_seconds


@app.exception_handler(LrclibRefreshTooSoon)
def lrclib_refresh_too_soon(
    request: Request, exc: LrclibRefreshTooSoon
) -> JSONResponse:
    """A 429 for a refresh from LRCLIB asked for too soon, saying how long
    the client should wait."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "This document's lyrics were checked against LRCLIB a moment ago.",
            "retry_after_seconds": exc.retry_after_seconds,
        },
    )


@app.exception_handler(LrclibUnavailable)
@app.exception_handler(YouTubeMusicUnavailable)
def upstream_unavailable(
    request: Request, exc: LrclibUnavailable | YouTubeMusicUnavailable
) -> JSONResponse:
    """A 502 for an upstream service (LRCLIB, YouTube Music) that couldn't
    be reached or understood."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


api = APIRouter(prefix="/api")
api.include_router(auth_router)


def _sanitize_lyrics(value: str) -> str | None:
    """`value` sanitized, or None if only whitespace is left."""
    value = sanitize_text(value)
    return value if value.strip() else None


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1)
    text: str | None = None
    youtube_video_id: str | None = None
    lrclib_uri: str | None = None

    @field_validator("youtube_video_id", "lrclib_uri")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("text")
    @classmethod
    def sanitize_text_or_none(cls, value: str | None) -> str | None:
        return None if value is None else _sanitize_lyrics(value)

    @model_validator(mode="after")
    def has_lyrics_source(self) -> "DocumentCreate":
        if self.text is None and self.lrclib_uri is None:
            raise ValueError("Enter the lyrics, or an LRCLIB track to load them from.")
        return self


class LineTiming(BaseModel):
    start: float
    end: float


class Document(BaseModel):
    id: int
    title: str
    text: str
    youtube_video_id: str | None
    lrclib_uri: str | None
    # Whether LRCLIB's lyrics replace the document's own, rather than the
    # document keeping them; None while it isn't linked.
    lrclib_replaces_text: bool | None
    # When each line of `text` is sung, in seconds into the track, from
    # LRCLIB's synced lyrics; None without them.
    lrclib_lines: list[LineTiming] | None
    # The line timings as edited on the document's page, used in place of
    # lrclib_lines: one per line, None for a line whose timing was deleted.
    # None without edits, or once `text` isn't what they were made for.
    edited_lines: list[LineTiming | None] | None = None
    created_at: datetime
    # Why a linked document's lyrics couldn't be refreshed from LRCLIB on
    # this load, in which case the stored ones are returned instead.
    lrclib_sync_error: str | None = None


def _fetch_lrclib_for_link(value: str) -> tuple[str, LrclibLyrics]:
    """The canonical address of the LRCLIB track `value` names, and its
    lyrics — or a 422 if LRCLIB refuses it."""
    try:
        uri = normalize_lrclib_uri(value)
        return uri, fetch_lyrics(uri)
    except LrclibError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@api.post("/documents", response_model=Document, status_code=201)
def create_document(document: DocumentCreate, user_id: CurrentUser) -> Document:
    """Create a document; given an LRCLIB track, its lyrics are used in
    place of `text`."""
    lrclib_uri = lyrics = None
    if document.lrclib_uri is not None:
        lrclib_uri, lyrics = _fetch_lrclib_for_link(document.lrclib_uri)

    with engine.begin() as conn:
        try:
            row = conn.execute(
                text(
                    f"""
                    INSERT INTO documents (
                        owner_id, title, text, youtube_video_id, lrclib_uri, lrclib_replaces_text, lrclib_lines,
                        lrclib_lines_text, lrclib_checked_at
                    )
                    VALUES (
                        :owner_id, :title, :text, :youtube_video_id, :lrclib_uri, :lrclib_replaces_text,
                        CAST(:lrclib_lines AS JSONB),
                        CASE WHEN :lrclib_lines IS NOT NULL THEN :text END,
                        CASE WHEN :lrclib_uri IS NOT NULL THEN now() END
                    )
                    RETURNING {DOCUMENT_COLUMNS}
                    """
                ),
                {
                    "owner_id": user_id,
                    "title": document.title,
                    "text": lyrics.text if lyrics else document.text,
                    "youtube_video_id": document.youtube_video_id,
                    "lrclib_uri": lrclib_uri,
                    "lrclib_replaces_text": True if lyrics else None,
                    "lrclib_lines": json_param(lyrics.lines if lyrics else None),
                },
            ).one()
        except IntegrityError as exc:
            with engine.connect() as lookup_conn:
                existing = lookup_conn.execute(
                    text(
                        "SELECT title FROM documents WHERE owner_id = :owner_id AND youtube_video_id = :youtube_video_id"
                    ),
                    {
                        "owner_id": user_id,
                        "youtube_video_id": document.youtube_video_id,
                    },
                ).one_or_none()

            detail = (
                f'A document with this YouTube video ID already exists: "{existing.title}".'
                if existing
                else "A document with this YouTube video ID already exists."
            )
            raise HTTPException(status_code=409, detail=detail) from exc

    return Document(**row._mapping)


# How long a linked document's lyrics are trusted before opening it checks
# LRCLIB for a new version.
LRCLIB_RECHECK_AFTER = timedelta(hours=24)
# How soon after the last check a manual refresh is allowed.
LRCLIB_REFRESH_COOLDOWN = timedelta(minutes=5)
# How long after a failed check opening the document shows that failure
# rather than asking LRCLIB again. It's also how long a new version can go
# unseen once LRCLIB is back, so it stays short.
LRCLIB_RETRY_FAILED_AFTER = timedelta(minutes=10)


def _time_left(checked_at: datetime | None, wait: timedelta) -> timedelta:
    """How much longer until `wait` has passed since `checked_at`; zero if it
    has, or if there was no check."""
    if checked_at is None:
        return timedelta(0)
    return max(checked_at + wait - datetime.now(UTC), timedelta(0))


@api.get("/documents/{document_id}", response_model=Document)
def get_document(document_id: OwnedDocument, user_id: CurrentUser) -> Document:
    """The document, its lyrics first refreshed from LRCLIB if it's linked
    to a track there and was last checked over `LRCLIB_RECHECK_AFTER` ago.
    A check that failed under `LRCLIB_RETRY_FAILED_AFTER` ago isn't retried:
    its error is shown with the stored lyrics instead."""
    with engine.connect() as conn:
        row = owned_document_row(conn, document_id, user_id)

    if row is None:
        raise study.DocumentNotFound()

    document = Document(**row._mapping)
    if document.lrclib_uri is None:
        return document
    if _time_left(row.lrclib_checked_at, LRCLIB_RECHECK_AFTER) > timedelta(0):
        return document
    if _time_left(row.lrclib_failed_at, LRCLIB_RETRY_FAILED_AFTER) > timedelta(0):
        return document.model_copy(update={"lrclib_sync_error": row.lrclib_failure})

    try:
        return _sync_with_lrclib(document_id, user_id, document.lrclib_uri)
    except (LrclibError, LrclibUnavailable) as exc:
        error = f"{exc} Showing the lyrics last loaded from it."
        _record_lrclib_failure(document_id, document.lrclib_uri, error)
        return document.model_copy(update={"lrclib_sync_error": error})


@api.post("/documents/{document_id}/lrclib/refresh", response_model=Document)
def refresh_lrclib(document_id: OwnedDocument, user_id: CurrentUser) -> Document:
    """Reload the linked document's lyrics from LRCLIB now, however recently
    they were checked — but no sooner than `LRCLIB_REFRESH_COOLDOWN` after
    the last check, so the button can't be used to hammer LRCLIB."""
    with engine.connect() as conn:
        row = owned_document_row(conn, document_id, user_id)

    if row is None:
        raise study.DocumentNotFound()
    if row.lrclib_uri is None:
        raise HTTPException(
            status_code=409, detail="This document isn't linked to LRCLIB."
        )
    wait = _time_left(row.lrclib_checked_at, LRCLIB_REFRESH_COOLDOWN)
    if wait > timedelta(0):
        raise LrclibRefreshTooSoon(wait.total_seconds())

    try:
        return _sync_with_lrclib(document_id, user_id, row.lrclib_uri)
    except (LrclibError, LrclibUnavailable) as exc:
        # Recorded so opening the document doesn't retry it straight away;
        # the refresh cooldown is left alone, so the button can retry it.
        _record_lrclib_failure(
            document_id,
            row.lrclib_uri,
            f"{exc} Showing the lyrics last loaded from it.",
        )
        if isinstance(exc, LrclibUnavailable):
            raise
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _record_lrclib_failure(document_id: int, uri: str, error: str) -> None:
    """Record that checking the document's lyrics against `uri` just failed
    with `error`, unless it has since been linked elsewhere."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE documents SET lrclib_failed_at = now(), lrclib_failure = :error
                WHERE id = :id AND lrclib_uri = :uri
                """
            ),
            {"id": document_id, "uri": uri, "error": error},
        )


def _sync_with_lrclib(document_id: int, user_id: int, uri: str) -> Document:
    """The document, linked to `uri`, with the lyrics LRCLIB has there now
    stored in it and the check recorded."""
    # Fetched with no transaction open, since LRCLIB can take seconds to
    # answer.
    lyrics = fetch_lyrics(uri)
    with engine.begin() as conn:
        current = _lock_document(conn, document_id, user_id)
        # Left alone if it was unlinked, or linked elsewhere, since `lyrics`
        # was fetched.
        if current.lrclib_uri != uri:
            return Document(**current._mapping)
        if _linked_lyrics(current.text, current.lrclib_replaces_text, lyrics) == (
            current.text,
            current.lrclib_lines,
        ):
            # Nothing changed, so only the check is written.
            row = conn.execute(
                text(
                    f"""
                    UPDATE documents
                    SET lrclib_checked_at = now(), lrclib_failed_at = NULL,
                        lrclib_failure = NULL
                    WHERE id = :id
                    RETURNING {DOCUMENT_COLUMNS}
                    """
                ),
                {"id": document_id},
            ).one()
            return Document(**row._mapping)
        return _store_lrclib_lyrics(
            conn, current, uri, lyrics, current.lrclib_replaces_text
        )


def _linked_lyrics(
    document_text: str, replaces_text: bool, lyrics: LrclibLyrics
) -> tuple[str, list[dict] | None]:
    """The text and line timings a document linked to LRCLIB takes from
    `lyrics`: LRCLIB's, if they replace its own; otherwise its own text,
    timed by LRCLIB only while LRCLIB's lyrics match it line for line."""
    if replaces_text:
        return lyrics.text, lyrics.lines
    # Blank lines at the end of the document, which synced lyrics can't
    # carry, just go untimed.
    return document_text, lyrics.lines if document_text.rstrip(
        "\n"
    ) == lyrics.text else None


def _lock_document(conn, document_id: int, user_id: int):
    """The row of the user's document, locked for the rest of the
    transaction; a 404 if they have no such document."""
    # The same lock a first tokens request takes to write, so writes to the
    # document can't interleave with one.
    current = owned_document_row(conn, document_id, user_id, for_update=True)
    if current is None:
        raise study.DocumentNotFound()
    return current


def _store_lrclib_lyrics(
    conn, current, uri: str, lyrics: LrclibLyrics, replace_text: bool
) -> Document:
    """Link the document whose locked row is `current` to `uri`, taking
    `lyrics`, just fetched from there, in place of its own if
    `replace_text` or else keeping its own, and return it. Tokens are only
    regenerated if the text changes, so readings picked for them survive an
    update to just the line timings."""
    new_text, lines = _linked_lyrics(current.text, replace_text, lyrics)
    # Changing the text drops its tokens, by the trigger from migration 0034.
    row = conn.execute(
        text(
            f"""
            UPDATE documents
            SET text = :text, lrclib_uri = :uri, lrclib_replaces_text = :replace_text,
                lrclib_lines = CAST(:lines AS JSONB),
                lrclib_lines_text = CASE WHEN :lines IS NOT NULL THEN :text END,
                lrclib_checked_at = now(), lrclib_failed_at = NULL, lrclib_failure = NULL
            WHERE id = :id
            RETURNING {DOCUMENT_COLUMNS}
            """
        ),
        {
            "id": current.id,
            "text": new_text,
            "uri": uri,
            "replace_text": replace_text,
            "lines": json_param(lines),
        },
    ).one()
    return Document(**row._mapping)


class DocumentTextUpdate(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def sanitize(cls, value: str) -> str:
        if (sanitized := _sanitize_lyrics(value)) is None:
            raise ValueError("Enter the lyrics.")
        return sanitized


@api.patch("/documents/{document_id}", response_model=Document)
def update_document_text(
    document_id: OwnedDocument, body: DocumentTextUpdate, user_id: CurrentUser
) -> Document:
    """Set the document's lyrics. A changed text drops every token derived
    from the old one, with no version history kept; the next tokens request
    processes it from scratch. The shared gloss_lookups cache, keyed by
    word rather than document, is kept.

    A document whose lyrics LRCLIB replaces takes them from there, so its
    text can't be edited until it's unlinked."""
    with engine.begin() as conn:
        # Its tokens are dropped by the trigger from migration 0034.
        row = conn.execute(
            text(
                f"""
                UPDATE documents SET text = :text
                WHERE id = :id AND owner_id = :owner_id AND lrclib_replaces_text IS NOT TRUE
                RETURNING {DOCUMENT_COLUMNS}
                """
            ),
            {"id": document_id, "owner_id": user_id, "text": body.text},
        ).one_or_none()

        if row is None:
            # The document is the caller's, or OwnedDocument would have
            # 404'd, so the only row the UPDATE can have missed is a linked
            # one.
            raise HTTPException(
                status_code=409,
                detail="This document's lyrics come from LRCLIB — unlink it to edit them.",
            )

    return Document(**row._mapping)


class LrclibLink(BaseModel):
    uri: str = Field(min_length=1)
    # False to keep the document's own lyrics and readings, taking only
    # LRCLIB's line timings while its lyrics match them.
    replace_text: bool = True


@api.put("/documents/{document_id}/lrclib", response_model=Document)
def link_lrclib(
    document_id: OwnedDocument, body: LrclibLink, user_id: CurrentUser
) -> Document:
    """Link the document to an LRCLIB track, either replacing its lyrics
    with the track's (readings picked for it are reset unless the text is
    the same) or keeping its lyrics and readings as they are."""
    uri, lyrics = _fetch_lrclib_for_link(body.uri)
    with engine.begin() as conn:
        return _store_lrclib_lyrics(
            conn,
            _lock_document(conn, document_id, user_id),
            uri,
            lyrics,
            body.replace_text,
        )


@api.delete("/documents/{document_id}/lrclib", response_model=Document)
def unlink_lrclib(document_id: OwnedDocument, user_id: CurrentUser) -> Document:
    """Stop loading the document's lyrics from LRCLIB, keeping the ones it
    has, which become editable."""
    # Its line timings are kept, since they still match its unchanged text.
    with engine.begin() as conn:
        row = conn.execute(
            text(
                f"""
                UPDATE documents SET lrclib_uri = NULL, lrclib_replaces_text = NULL
                WHERE id = :id AND owner_id = :owner_id
                RETURNING {DOCUMENT_COLUMNS}
                """
            ),
            {"id": document_id, "owner_id": user_id},
        ).one_or_none()

    if row is None:
        raise study.DocumentNotFound()
    return Document(**row._mapping)


class LineTimingsUpdate(BaseModel):
    # The lyrics the timings were edited for, so edits the lyrics changed
    # underneath are refused.
    text: str
    # One per line of `text`, None for a blank line left untimed.
    lines: list[LineTiming | None]

    @field_validator("lines")
    @classmethod
    def in_order(cls, lines: list[LineTiming | None]) -> list[LineTiming | None]:
        timed = [line for line in lines if line is not None]
        if any(line.start < 0 or line.end < line.start for line in timed):
            raise ValueError(
                "A line can't start before the song does, or end before it starts."
            )
        if any(later.start < earlier.start for earlier, later in pairwise(timed)):
            raise ValueError("A line can't start before the line before it.")
        return lines


@api.put("/documents/{document_id}/timings", response_model=Document)
def save_line_timings(
    document_id: OwnedDocument, body: LineTimingsUpdate, user_id: CurrentUser
) -> Document:
    """Save `body.lines` as the document's line timings, used in place of
    LRCLIB's for as long as its lyrics stay `body.text`."""
    with engine.begin() as conn:
        current = _lock_document(conn, document_id, user_id)
        if current.text != body.text:
            raise HTTPException(
                status_code=409,
                detail="These lyrics changed while their timings were being edited — reload to edit them again.",
            )
        text_lines = current.text.split("\n")
        if len(body.lines) > len(text_lines):
            raise HTTPException(
                status_code=422, detail="There are more timings than lines."
            )
        # Blank lines, between stanzas, are the only ones that may go untimed.
        if any(
            line.strip() and (i >= len(body.lines) or body.lines[i] is None)
            for i, line in enumerate(text_lines)
        ):
            raise HTTPException(
                status_code=422, detail="Every line with lyrics needs a timing."
            )
        row = conn.execute(
            text(
                f"""
                UPDATE documents SET edited_lines = CAST(:lines AS JSONB), edited_lines_text = :text
                WHERE id = :id
                RETURNING {DOCUMENT_COLUMNS}
                """
            ),
            {
                "id": document_id,
                "lines": json_param(
                    [line.model_dump() if line else None for line in body.lines]
                ),
                "text": current.text,
            },
        ).one()
    return Document(**row._mapping)


SortField = Literal["id", "title", "youtube_video_id", "created_at", "readiness"]


class DocumentListItem(BaseModel):
    id: int
    title: str
    youtube_video_id: str | None
    created_at: datetime
    readiness: study.Readiness


class DocumentPage(BaseModel):
    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


@api.get("/documents", response_model=DocumentPage)
def list_documents(
    user_id: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: SortField = "created_at",
    sort_dir: Literal["asc", "desc"] = "desc",
) -> DocumentPage:
    direction = "ASC" if sort_dir == "asc" else "DESC"
    offset = (page - 1) * page_size
    by_readiness = sort_by == "readiness"
    # Readiness is computed from the schedule, not stored, so ordering by it
    # takes every song's, and the page is cut from the sorted list.
    order_by = "id" if by_readiness else sort_by
    paging = "" if by_readiness else "LIMIT :limit OFFSET :offset"

    # A transaction, since the gloss of a word the cache has lost is looked up
    # again and stored.
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT id, title, youtube_video_id, created_at,
                       COUNT(*) OVER() AS total
                FROM documents
                WHERE owner_id = :owner_id
                ORDER BY {order_by} {direction}, id {direction}
                {paging}
                """
            ),
            {"owner_id": user_id, "limit": page_size, "offset": offset},
        ).all()
        readiness = study.documents_readiness(conn, user_id, [row.id for row in rows])

    total = rows[0].total if rows else 0
    if by_readiness:
        # Stable, so songs equally ready stay in id order.
        rows.sort(
            key=lambda row: readiness[row.id].readiness, reverse=sort_dir == "desc"
        )
        rows = rows[offset : offset + page_size]
    items = [
        DocumentListItem(
            id=row.id,
            title=row.title,
            youtube_video_id=row.youtube_video_id,
            created_at=row.created_at,
            readiness=readiness[row.id],
        )
        for row in rows
    ]

    return DocumentPage(items=items, total=total, page=page, page_size=page_size)


class JmdictSense(BaseModel):
    pos: list[str]
    misc: list[str]
    field: list[str]
    gloss: list[str]


class JmdictEntry(BaseModel):
    idseq: int
    kanji_forms: list[str]
    kana_forms: list[str]
    senses: list[JmdictSense]


@api.get("/jmdict/search", response_model=list[JmdictEntry])
def jmdict_search(
    q: str = Query(min_length=1),
    max_results_per_tier: int = Query(default=3, ge=1, le=20),
) -> list[JmdictEntry]:
    return [
        JmdictEntry(**entry)
        for entry in search_jmdict(q, max_results_per_tier=max_results_per_tier)
    ]


@api.get("/songs/search", response_model=list[Song])
def songs_search(
    user_id: CurrentUser,
    q: str = Query(min_length=1),
    videos: bool = False,
):
    return search_songs(q, videos)


@api.get("/lrclib/search", response_model=list[LrclibCandidate])
def lrclib_search(
    user_id: CurrentUser,
    title: str = "",
    artist: str = "",
    # In seconds; left out when the song's length isn't known.
    duration: float | None = Query(default=None, gt=0),
):
    if not title.strip() and not artist.strip():
        raise HTTPException(422, "Enter a title or an artist to search for.")
    return search_tracks(title, artist, duration)


class LrclibTrackLyrics(BaseModel):
    text: str
    # One per line of `text`, or None when the track's lyrics aren't synced.
    lines: list[LineTiming] | None


@api.get("/lrclib/tracks/{track_id}", response_model=LrclibTrackLyrics)
def lrclib_track_lyrics(track_id: int, user_id: CurrentUser) -> LrclibTrackLyrics:
    """The lyrics LRCLIB's track `track_id` has now, as linking it would
    load them — or a 422 if LRCLIB refuses it."""
    _, lyrics = _fetch_lrclib_for_link(str(track_id))
    return LrclibTrackLyrics(text=lyrics.text, lines=lyrics.lines)


class GlossSense(JmdictSense):
    entry_idseq: int


class GlossPiece(BaseModel):
    surface: str
    reading: str
    senses: list[GlossSense]
    ambiguous_readings: list[str]
    # Whether this is a word, rather than grammar (see app.glosses.is_word_piece).
    is_word: bool
    # What a grammar word or helper verb adds to the word before it, for a
    # piece of a group's gloss (see app.grammar.grammar_note).
    note: str | None = None


class Gloss(BaseModel):
    reading: str
    # What this was looked up under — usually the token's own
    # dictionary_form, but for a merged group (phrase_start_position set)
    # the phrase's headword (この期に及んで) or the group's parts
    # (欲する＋てる＋ん＋だ＋って).
    lookup_form: str
    senses: list[GlossSense]
    source: str
    pieces: list[GlossPiece] = []
    # The hiragana this was looked up as, for katakana with no dictionary
    # entry of its own (see app/katakana.py).
    looked_up_as: str | None = None


class Conflict(BaseModel):
    id: int
    kind: str
    value: dict
    selected: bool


class Token(BaseModel):
    id: int
    document_id: int
    position: int
    char_begin: int
    char_end: int
    surface: str
    dictionary_form: str
    dictionary_form_reading: str
    dictionary_form_note: str | None
    normalized_form: str
    reading_katakana: str
    part_of_speech: list[str]
    is_oov: bool
    furigana_spans: list[dict]
    needs_review: bool
    review_reason: str | None
    furigana_override: list[dict] | None
    # Marked by the user as needing no gloss, like a name no dictionary has.
    gloss_ignored: bool
    # The first token's position when this token is merged with its
    # neighbors into one group, the same across the group; else None.
    phrase_start_position: int | None
    # What that group is: an accepted phrase suggestion (see
    # app/phrase_merge.py), or a predicate with its grammar (see
    # app/grammar.py).
    group_kind: Literal["phrase", "predicate"] | None
    is_english: bool
    gloss: Gloss | None
    conflicts: list[Conflict]
    start_time: Decimal | None
    end_time: Decimal | None


class _FetchedTokens(NamedTuple):
    tokens: list[Token]
    # Some token that should have a gloss linked has none.
    unlinked: bool
    # Some composite gloss has a piece whose lookup isn't cached, so it was
    # shown with no gloss (only under `cache_only`).
    dropped_lookup: bool


def _fetch_tokens(
    conn,
    document_id: int,
    token_ids: list[int] | None = None,
    *,
    cache_only: bool = False,
) -> list[Token]:
    """The document's tokens (or just `token_ids`) as shown. With
    `cache_only`, for a connection whose work is rolled back, a composite
    gloss with a piece whose lookup isn't cached comes back with no gloss,
    as an unlinked token does, rather than looking it up to be lost.
    """
    return _read_tokens(conn, document_id, token_ids, cache_only=cache_only).tokens


def _read_tokens(
    conn,
    document_id: int,
    token_ids: list[int] | None = None,
    *,
    cache_only: bool = False,
) -> _FetchedTokens:
    """What `_fetch_tokens` returns, along with which repairs the tokens
    need before they can be shown fully glossed."""
    token_filter = "AND t.id = ANY(:token_ids)" if token_ids is not None else ""
    rows = conn.execute(
        text(
            f"""
            SELECT t.id, t.document_id, t.position, t.char_begin, t.char_end, t.surface,
                   t.dictionary_form, t.normalized_form, t.reading_katakana,
                   t.part_of_speech, t.is_oov, t.furigana_spans, t.needs_review,
                   t.review_reason, t.furigana_override, t.gloss_ignored, t.start_time, t.end_time,
                   t.phrase_start_position,
                   CASE
                       WHEN t.phrase_start_position IS NULL THEN NULL
                       WHEN {IS_ACCEPTED_PHRASE_SQL} THEN 'phrase'
                       ELSE 'predicate'
                   END AS group_kind,
                   gl.reading AS gloss_reading, gl.entries AS gloss_entries, gl.source AS gloss_source,
                   gl.lookup_form AS gloss_lookup_form,
                   {KATAKANA_GLOSS_COLUMNS}
            FROM tokens t
            LEFT JOIN gloss_lookups gl ON gl.id = t.gloss_lookup_id
            WHERE t.document_id = :document_id {token_filter}
            ORDER BY t.position
            """
        ),
        {"document_id": document_id, "token_ids": token_ids},
    ).all()
    if not rows:
        return _FetchedTokens([], False, False)

    conflict_rows = conn.execute(
        text(
            f"""
            SELECT c.id, c.token_id, c.kind, c.value, c.selected
            FROM conflicts c
            JOIN tokens t ON t.id = c.token_id
            WHERE t.document_id = :document_id {token_filter}
            ORDER BY c.id
            """
        ),
        {"document_id": document_id, "token_ids": token_ids},
    ).all()
    conflicts_by_token: dict[int, list[Conflict]] = {}
    for c in conflict_rows:
        conflicts_by_token.setdefault(c.token_id, []).append(
            Conflict(id=c.id, kind=c.kind, value=c.value, selected=c.selected)
        )

    # Each composite gloss as its token shows it: a katakana token's with the
    # words picked for its pieces.
    composites = {
        row.id: picked_katakana_gloss(row) if row.katakana_gloss else row.gloss_entries
        for row in rows
        if row.gloss_source == "composite"
    }

    # Every composite's pieces' lookups, in one read.
    lookups = piece_lookups(conn, composites.values(), cache_only=cache_only)
    shown_pieces_memo: dict[str, list[dict] | None] = {}
    tokens = []
    unlinked = False
    dropped_lookup = False
    for row in rows:
        data = dict(row._mapping)
        gloss_reading = data.pop("gloss_reading")
        gloss_entries = data.pop("gloss_entries")
        gloss_source = data.pop("gloss_source")
        gloss_lookup_form = data.pop("gloss_lookup_form")
        # Already applied to the gloss, in composites.
        data.pop("katakana_picks")
        data.pop("katakana_gloss")
        conflicts = conflicts_by_token.get(row.id, [])
        if gloss_reading is None:
            data["gloss"] = None
            unlinked = unlinked or is_glossable(row.part_of_speech, bool(conflicts))
        elif gloss_source == "composite":
            composite = composites[row.id]
            # Each piece ranked for its own part of speech, not the token's.
            entries_key = json.dumps(composite, sort_keys=True)
            if entries_key not in shown_pieces_memo:
                shown_pieces_memo[entries_key] = shown_pieces(composite, lookups)
            pieces = shown_pieces_memo[entries_key]
            dropped_lookup = dropped_lookup or pieces is None
            # None only under cache_only, for a piece whose lookup isn't
            # cached: shown unglossed, as an unlinked token is.
            data["gloss"] = (
                None
                if pieces is None
                else Gloss(
                    reading=gloss_reading,
                    lookup_form=gloss_lookup_form,
                    senses=[],
                    source=gloss_source,
                    pieces=[GlossPiece(**piece) for piece in pieces],
                    looked_up_as=gloss_entries.get("looked_up_as"),
                )
            )
        else:
            data["gloss"] = Gloss(
                reading=gloss_reading,
                lookup_form=gloss_lookup_form,
                senses=rank_senses(gloss_entries, data["part_of_speech"][0]),
                source=gloss_source,
            )
        data["conflicts"] = conflicts
        data["is_english"] = is_probably_english(data["surface"])
        data["dictionary_form_reading"] = mixed_reading(data["dictionary_form"])
        data["dictionary_form_note"] = dictionary_form_note(
            data["dictionary_form"], data["normalized_form"], data["part_of_speech"][4]
        )
        tokens.append(Token(**data))
    return _FetchedTokens(tokens, unlinked, dropped_lookup)


def _fetch_token(conn, document_id: int, token_id: int) -> Token:
    """A single token, scoped by id — for the resolve/correct endpoints,
    which only ever need to return the one token they just mutated. Avoids
    re-fetching and re-ranking every other token in the document just to
    pick one row back out."""
    return _fetch_tokens(conn, document_id, token_ids=[token_id])[0]


class DocumentTokens(BaseModel):
    status: Literal["processing", "ready", "failed"]
    # Empty until they're ready.
    tokens: list[Token] = []
    # Why processing failed, if it did.
    detail: str | None = None


# A failed job's details are in the server's log.
PROCESSING_FAILED = "Adding furigana and glosses failed."


def _document_tokens(document_id: int, *, retry: bool) -> DocumentTokens:
    """The document's tokens, if it's been processed; otherwise starts it
    processing, unless it already is or — unless `retry` — it failed, and
    says which."""
    with engine.connect() as conn:
        fetched = _read_tokens(conn, document_id, cache_only=True)

    if fetched.tokens:
        if not fetched.unlinked and not fetched.dropped_lookup:
            return DocumentTokens(status="ready", tokens=fetched.tokens)
    else:
        progress = processing.start(document_id, retry=retry)
        if progress is None:
            raise study.DocumentNotFound()
        if progress == "processing":
            return DocumentTokens(status="processing")
        if progress == "failed":
            return DocumentTokens(status="failed", detail=PROCESSING_FAILED)
        # Processed since its tokens were read above, or it has none to make.

    with engine.begin() as conn:
        # Tokens missing their gloss link: tokenized before gloss support
        # existed, or unlinked by a migration that reset the gloss cache (as
        # 0005 did).
        if fetched.unlinked:
            repair_gloss_links(conn, document_id)
        # A piece of a composite gloss with no cached lookup is left alone by
        # repair_gloss_links: the fetch, which can write, looks it up.
        return DocumentTokens(status="ready", tokens=_fetch_tokens(conn, document_id))


@api.get("/documents/{document_id}/tokens", response_model=DocumentTokens)
def get_document_tokens(
    document_id: OwnedDocument, user_id: CurrentUser
) -> DocumentTokens:
    """The document's tokens, or how processing them is going: what a page
    polls until they're ready. Starts processing them if nothing is, but
    never again after it failed, which polling would repeat forever."""
    return _document_tokens(document_id, retry=False)


@api.post("/documents/{document_id}/tokens/processing", response_model=DocumentTokens)
def process_document_tokens(
    document_id: OwnedDocument, user_id: CurrentUser
) -> DocumentTokens:
    """The document's tokens, or how processing them is going, having
    started processing them unless they are or have been — even if that
    failed last time, which this tries again."""
    return _document_tokens(document_id, retry=True)


class ConflictResolution(BaseModel):
    conflict_id: int


@api.post("/documents/{document_id}/tokens/{token_id}/resolve", response_model=Token)
def resolve_token_conflict(
    document_id: OwnedDocument,
    token_id: int,
    body: ConflictResolution,
    user_id: CurrentUser,
) -> Token:
    with engine.begin() as conn:
        resolve_conflict(conn, document_id, token_id, body.conflict_id)

        return _fetch_token(conn, document_id, token_id)


class PhraseAcceptance(BaseModel):
    conflict_ids: list[int] = Field(min_length=1)


@api.post("/documents/{document_id}/tokens/accept-phrases", response_model=list[Token])
def accept_phrase_suggestions_endpoint(
    document_id: OwnedDocument, body: PhraseAcceptance, user_id: CurrentUser
) -> list[Token]:
    """Apply each of `conflict_ids` — phrase suggestions, or split predicate
    groups to merge again — as accept_phrase_suggestions does. Returns every
    token they changed."""
    with engine.begin() as conn:
        affected = accept_phrase_suggestions(conn, document_id, body.conflict_ids)

        return _fetch_tokens(conn, document_id, token_ids=affected)


@api.post("/documents/{document_id}/tokens/phrase-furigana", response_model=list[Token])
def resolve_phrase_furigana_endpoint(
    document_id: OwnedDocument, body: ConflictResolution, user_id: CurrentUser
) -> list[Token]:
    """Apply `conflict_id`, one of a phrase's alternative furigana splits.
    Returns the tokens it changed."""
    with engine.begin() as conn:
        affected = resolve_phrase_furigana(conn, document_id, body.conflict_id)

        return _fetch_tokens(conn, document_id, token_ids=affected)


@api.post(
    "/documents/{document_id}/tokens/{token_id}/unmerge-phrase",
    response_model=list[Token],
)
def unmerge_phrase_tokens(
    document_id: OwnedDocument, token_id: int, user_id: CurrentUser
) -> list[Token]:
    """Split the group token_id is merged into, found from any member of it.
    Returns the tokens it changed."""
    with engine.begin() as conn:
        affected = unmerge_phrase(conn, document_id, token_id)

        if not affected:
            return []
        return _fetch_tokens(conn, document_id, token_ids=affected)


@api.get(
    "/documents/{document_id}/tokens/{token_id}/alternate-readings",
    response_model=list[dict],
)
def get_alternate_readings(
    document_id: OwnedDocument, token_id: int, user_id: CurrentUser
) -> list[dict]:
    """Every reading token_id can be given (see token_reading_options), as
    options to apply through /tokens/reading."""
    with engine.connect() as conn:
        return token_reading_options(conn, document_id, token_id)


_KANA_ONLY_RE = re.compile(r"^[ぁ-んァ-ヶー]+$")


class ReadingCorrection(BaseModel):
    reading: str = Field(min_length=1)

    @field_validator("reading")
    @classmethod
    def kana_only(cls, value: str) -> str:
        if not _KANA_ONLY_RE.match(value):
            raise ValueError("Reading must be hiragana and/or katakana only.")
        return value


@api.post("/documents/{document_id}/tokens/{token_id}/correct", response_model=Token)
def correct_token_reading(
    document_id: OwnedDocument,
    token_id: int,
    body: ReadingCorrection,
    user_id: CurrentUser,
) -> Token:
    with engine.begin() as conn:
        correct_reading(conn, document_id, token_id, body.reading)

        return _fetch_token(conn, document_id, token_id)


class TokenIds(BaseModel):
    token_ids: list[int] = Field(min_length=1)

    @field_validator("token_ids")
    @classmethod
    def distinct(cls, value: list[int]) -> list[int]:
        # A group is checked by counting how many of these were found.
        return sorted(set(value))


class TokensReading(ReadingCorrection, TokenIds):
    # The furigana split to prefer among the tokens' options with `reading`.
    furigana_spans: list[dict] | None = None


@api.post("/documents/{document_id}/tokens/reading", response_model=list[Token])
def apply_tokens_reading(
    document_id: OwnedDocument, body: TokensReading, user_id: CurrentUser
) -> list[Token]:
    """Select `reading` for each of the document's tokens in `token_ids`,
    which must be one word read and parsed the same way, as select_reading
    does. Returns every token whose gloss changed, which includes the rest
    of any group one of them is in."""
    with engine.begin() as conn:
        affected = select_reading(
            conn, document_id, body.token_ids, body.reading, body.furigana_spans
        )
        return _fetch_tokens(conn, document_id, token_ids=affected)


class TokensIgnored(TokenIds):
    ignored: bool


@api.post("/documents/{document_id}/tokens/ignored", response_model=list[Token])
def set_tokens_ignored(
    document_id: OwnedDocument, body: TokensIgnored, user_id: CurrentUser
) -> list[Token]:
    """Mark each of the document's tokens in `token_ids`, which must be one
    word read and parsed the same way, as needing no gloss, or not."""
    with engine.begin() as conn:
        lock_token_group(conn, document_id, body.token_ids)
        conn.execute(
            text(
                "UPDATE tokens SET gloss_ignored = :ignored WHERE id = ANY(:token_ids)"
            ),
            {"token_ids": body.token_ids, "ignored": body.ignored},
        )
        return _fetch_tokens(conn, document_id, token_ids=body.token_ids)


class WordOption(BaseModel):
    # Its JMDict entry, which picks it.
    idseq: int
    spelling: str
    # The glosses of its first sense.
    gloss: list[str]
    # Whether the piece is this word now: the one picked for it, or else the
    # one its gloss guesses.
    current: bool


@api.get(
    "/documents/{document_id}/tokens/{token_id}/pieces/{piece}/words",
    response_model=list[WordOption],
)
def get_piece_words(
    document_id: OwnedDocument, token_id: int, piece: int, user_id: CurrentUser
) -> list[WordOption]:
    """The words piece `piece` of token_id's gloss could be, for a token sung
    in katakana: every word JMDict has with the piece's reading, to pick
    from through /tokens/piece-word."""
    # A transaction, since a lookup the cache doesn't have is stored.
    with engine.begin() as conn:
        options = piece_word_options(conn, document_id, token_id, piece)
    return [WordOption(**option) for option in options]


class PieceWordPick(TokenIds):
    piece: int = Field(ge=0)
    # The word's JMDict entry, as a WordOption names it.
    idseq: int


@api.post("/documents/{document_id}/tokens/piece-word", response_model=list[Token])
def pick_piece_word_endpoint(
    document_id: OwnedDocument, body: PieceWordPick, user_id: CurrentUser
) -> list[Token]:
    """Pick a word for a piece of the tokens' gloss, as pick_piece_word
    does. Returns the tokens."""
    with engine.begin() as conn:
        pick_piece_word(conn, document_id, body.token_ids, body.piece, body.idseq)
        return _fetch_tokens(conn, document_id, token_ids=body.token_ids)


class StudyCard(BaseModel):
    id: int
    kind: CardKind
    lookup_form: str
    # None for a grammar term.
    reading: str | None
    # The JMDict entry of a word picked for a piece of katakana, which tells
    # apart two read and written alike; None for any other.
    idseq: int | None
    # Removed from study, keeping its history.
    suspended: bool
    due: datetime
    first_seen_document_id: int | None


class QueuedCard(StudyCard):
    # None when the card's word is in none of the user's songs any more.
    line: Line | None
    # In the order to show them.
    options: list[Option]
    # The index of the right option; None, with no options, for a word with
    # no dictionary entry to ask about any more.
    answer: int | None
    # A word's every sense, ranked, for the reveal; its options show the
    # first two.
    senses: list[GlossSense]
    # Each kanji of the word, or the group it's in, as it's used there, for
    # the reveal. The rest of what its sidebar shows is in StudyQueue.kanji.
    kanji: list[CardKanji]


class StudyQueue(BaseModel):
    cards: list[QueuedCard]
    # The sidebar entry of every kanji of the cards, by character, sent once
    # however many cards have it. Its deck_words may include the card it's
    # shown on, which the sidebar leaves out, and one more word than it shows.
    kanji: dict[str, KanjiEntry]
    # How many deck_words the sidebar lists under a kanji.
    max_deck_words: int = MAX_DECK_WORDS


def _study_queue(queue: Queue) -> StudyQueue:
    return StudyQueue(
        cards=[
            QueuedCard(**row._mapping, **dataclasses.asdict(content))
            for row, content in queue.cards
        ],
        kanji=queue.kanji,
    )


class DocumentWord(BaseModel):
    # Every token of the word and what's glossed with it.
    token_ids: list[int]
    # For a word or grammar term that's one piece of a gloss (a katakana
    # token's or a group's), which one.
    piece: int | None
    kind: CardKind
    lookup_form: str
    # None for a grammar term.
    reading: str | None
    # As on a card (see StudyCard).
    idseq: int | None
    # How it can be corrected, as on a card (see card_content.Line).
    correction: Literal["reading", "word"] | None
    # The user's card for it, removed or not; None if they have none.
    card: StudyCard | None


@api.get("/documents/{document_id}/words", response_model=list[DocumentWord])
def get_document_words(
    document_id: OwnedDocument, user_id: CurrentUser
) -> list[DocumentWord]:
    """Every word and grammar term of the document the user could add to
    their cards, where it is, with their card for it if they have one."""
    # A transaction, since a gloss the cache has lost is looked up again and
    # stored.
    with engine.begin() as conn:
        words = document_words(conn, user_id, document_id)
    return [
        DocumentWord(
            token_ids=word.token_ids,
            piece=word.piece,
            kind=word.key.kind,
            lookup_form=word.key.lookup_form,
            reading=word.key.reading,
            idseq=word.key.idseq,
            correction=word.correction,
            card=StudyCard(**word.card._mapping) if word.card else None,
        )
        for word in words
    ]


@api.put("/documents/{document_id}/tokens/{token_id}/card", response_model=StudyCard)
def add_token_card(
    document_id: OwnedDocument,
    token_id: int,
    user_id: CurrentUser,
    piece: int | None = Query(default=None, ge=0),
) -> StudyCard:
    """Add the word `token_id` is part of to the user's cards, or restore it
    if they removed it, as enroll_token does. `piece` names which word or
    grammar term of a gloss's pieces, for a token sung in katakana or in a
    group."""
    with engine.begin() as conn:
        row = enroll_token(conn, user_id, document_id, token_id, piece)
    return StudyCard(**row._mapping)


class ReviewAnswer(BaseModel):
    correct: bool
    duration_ms: int = Field(ge=0)
    # The song whose line was played, if any.
    document_id: int | None = None


class ReviewResult(BaseModel):
    # FSRS's rating, 1 (Again) to 4 (Easy).
    rating: int
    # For a correction to undo it (CardLineCorrection.review_id).
    review_id: int
    card: StudyCard


class PushOut(BaseModel):
    months: study.PushOutMonths


@api.post("/cards/{card_id}/review", response_model=ReviewResult)
def review_card(
    card_id: int, answer: ReviewAnswer, user_id: CurrentUser
) -> ReviewResult:
    """Schedule the user's card after an answer, rated from its correctness
    and how long it took."""
    with engine.begin() as conn:
        rating, review_id, row = study.review_card(
            conn,
            user_id,
            card_id,
            answer.correct,
            answer.duration_ms,
            answer.document_id,
        )
    return ReviewResult(
        rating=int(rating), review_id=review_id, card=StudyCard(**row._mapping)
    )


@api.post("/cards/{card_id}/push-out", response_model=StudyCard)
def push_out_card(card_id: int, body: PushOut, user_id: CurrentUser) -> StudyCard:
    """Reschedule the user's card 1, 3 or 6 months out, for a word they
    already knew. Not a review: nothing is logged."""
    with engine.begin() as conn:
        row = study.push_out(conn, user_id, card_id, body.months)
    return StudyCard(**row._mapping)


@api.post("/cards/{card_id}/suspend", response_model=StudyCard)
def suspend_card(card_id: int, user_id: CurrentUser) -> StudyCard:
    """Remove the user's card from study, keeping its history; adding the
    word again (add_token_card) restores it."""
    with engine.begin() as conn:
        row = study.suspend_card(conn, user_id, card_id)
    return StudyCard(**row._mapping)


class CardLineCorrection(BaseModel):
    # The token whose word to correct: the card's line's.
    document_id: int
    token_id: int
    # The card's review from that line, if it was answered, to undo: it was
    # asked about the wrong word.
    review_id: int | None = None


class CardReadingCorrection(CardLineCorrection, ReadingCorrection):
    furigana_spans: list[dict] | None = None


class CardWordCorrection(CardLineCorrection):
    # Which of the gloss's pieces of the token, sung in katakana.
    piece: int = Field(ge=0)
    # The word's JMDict entry, as a WordOption names it.
    idseq: int


class CardCorrection(BaseModel):
    # The user's card for the word the line has now; None if it has no
    # dictionary entry to study.
    card: StudyCard | None
    # Whether the card corrected was kept, which it is once it has reviews.
    kept: bool


def _correct_card(
    user_id: int,
    card_id: int,
    body: CardLineCorrection,
    piece: int | None,
    correct: Callable[[object], object],
) -> CardCorrection:
    """study.correct_card in a transaction of its own, as a response."""
    with engine.begin() as conn:
        card, kept = study.correct_card(
            conn,
            user_id,
            card_id,
            body.document_id,
            body.token_id,
            piece,
            correct,
            body.review_id,
        )
    return CardCorrection(card=StudyCard(**card._mapping) if card else None, kept=kept)


@api.post("/cards/{card_id}/reading", response_model=CardCorrection)
def correct_card_reading(
    card_id: int, body: CardReadingCorrection, user_id: CurrentUser
) -> CardCorrection:
    """Select `reading` for the token the user's card was being studied
    from, as /tokens/reading does, as study.correct_card does. Nothing is
    logged."""
    return _correct_card(
        user_id,
        card_id,
        body,
        None,
        lambda conn: select_reading(
            conn, body.document_id, [body.token_id], body.reading, body.furigana_spans
        ),
    )


@api.post("/cards/{card_id}/word", response_model=CardCorrection)
def correct_card_word(
    card_id: int, body: CardWordCorrection, user_id: CurrentUser
) -> CardCorrection:
    """Pick a word for a piece of the katakana token the user's card was
    being studied from, as /tokens/piece-word does, as study.correct_card
    does. Nothing is logged."""
    return _correct_card(
        user_id,
        card_id,
        body,
        body.piece,
        lambda conn: pick_piece_word(
            conn, body.document_id, [body.token_id], body.piece, body.idseq
        ),
    )


@api.get("/study/queue", response_model=StudyQueue)
def get_all_songs_queue(user_id: CurrentUser) -> StudyQueue:
    """The user's cards that are due, from every song, each with a line to
    play from any song that has its word and the options to answer it
    from."""
    # A transaction, since a gloss the cache has lost is looked up again
    # and stored.
    with engine.begin() as conn:
        return _study_queue(study.all_songs_queue(conn, user_id))


@api.post("/documents/{document_id}/study", response_model=StudyQueue)
def start_song_session(document_id: OwnedDocument, user_id: CurrentUser) -> StudyQueue:
    """Start studying the song: enroll new words from it, up to its daily
    limit, and return the user's due cards for its words, each with a line
    of the song to play and the options to answer it from."""
    with engine.begin() as conn:
        return _study_queue(study.song_queue(conn, user_id, document_id))


@api.get("/documents/{document_id}/readiness", response_model=study.Readiness)
def get_song_readiness(
    document_id: OwnedDocument, user_id: CurrentUser
) -> study.Readiness:
    """How ready the user is for the song as of now."""
    with engine.begin() as conn:
        readiness = study.documents_readiness(conn, user_id, [document_id])
    return readiness[document_id]


class RunThrough(BaseModel):
    youtube_video_id: str | None
    lines: list[RunLine]


@api.get("/documents/{document_id}/run-through", response_model=RunThrough)
def get_run_through(document_id: OwnedDocument, user_id: CurrentUser) -> RunThrough:
    """The song's lines in order, each with the words in it that the user's
    cards say they're forgetting, for playing it through and pausing on
    those. Not a review: nothing is logged and no card moves."""
    with engine.begin() as conn:
        video_id, lines = study.run_through(conn, user_id, document_id)
    return RunThrough(youtube_video_id=video_id, lines=lines)


class StudySettings(BaseModel):
    desired_retention: float = Field(ge=study.MIN_RETENTION, le=study.MAX_RETENTION)


@api.get("/study/settings", response_model=StudySettings)
def get_study_settings(user_id: CurrentUser) -> StudySettings:
    """The user's study settings."""
    with engine.connect() as conn:
        return StudySettings(
            desired_retention=study.get_desired_retention(conn, user_id)
        )


@api.put("/study/settings", response_model=StudySettings)
def save_study_settings(settings: StudySettings, user_id: CurrentUser) -> StudySettings:
    """Save the user's study settings. A new desired retention applies from
    each card's next review; due dates already set stay as they are."""
    with engine.begin() as conn:
        return StudySettings(
            desired_retention=study.set_desired_retention(
                conn, user_id, settings.desired_retention
            )
        )


class SongStudySettings(BaseModel):
    new_cards_per_day: int = Field(ge=0)


@api.get("/documents/{document_id}/study/settings", response_model=SongStudySettings)
def get_song_study_settings(
    document_id: OwnedDocument, user_id: CurrentUser
) -> SongStudySettings:
    """The study settings of one of the user's songs."""
    with engine.connect() as conn:
        return SongStudySettings(
            new_cards_per_day=study.get_new_cards_per_day(conn, user_id, document_id)
        )


@api.put("/documents/{document_id}/study/settings", response_model=SongStudySettings)
def save_song_study_settings(
    document_id: OwnedDocument, settings: SongStudySettings, user_id: CurrentUser
) -> SongStudySettings:
    """Save the study settings of one of the user's songs."""
    with engine.begin() as conn:
        return SongStudySettings(
            new_cards_per_day=study.set_new_cards_per_day(
                conn, user_id, document_id, settings.new_cards_per_day
            )
        )


app.include_router(api)
