import dataclasses
import json
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.conflicts import (
    ConflictNotFound,
    TokenNotFound,
    correct_reading,
    create_conflicts,
    resolve_conflict,
)
from app.db import engine
from app.glosses import (
    GlossPlan,
    attach_glosses,
    gloss_key,
    is_glossable,
    is_probably_english,
    plan_glosses,
    rank_senses,
    search_jmdict,
    store_glosses,
)
from app.tokenization import TokenRecord, dictionary_form_note, mixed_reading, tokenize_document

app = FastAPI()

allowed_origins = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    youtube_video_id: Optional[str] = None

    @field_validator("youtube_video_id")
    @classmethod
    def blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None


class Document(BaseModel):
    id: int
    title: str
    text: str
    youtube_video_id: Optional[str]
    created_at: datetime


@app.post("/documents", response_model=Document, status_code=201)
def create_document(document: DocumentCreate) -> Document:
    with engine.begin() as conn:
        try:
            row = conn.execute(
                text(
                    """
                    INSERT INTO documents (title, text, youtube_video_id)
                    VALUES (:title, :text, :youtube_video_id)
                    RETURNING id, title, text, youtube_video_id, created_at
                    """
                ),
                {
                    "title": document.title,
                    "text": document.text,
                    "youtube_video_id": document.youtube_video_id,
                },
            ).one()
        except IntegrityError as exc:
            with engine.connect() as lookup_conn:
                existing = lookup_conn.execute(
                    text("SELECT title FROM documents WHERE youtube_video_id = :youtube_video_id"),
                    {"youtube_video_id": document.youtube_video_id},
                ).one_or_none()

            detail = (
                f'A document with this YouTube video ID already exists: "{existing.title}".'
                if existing
                else "A document with this YouTube video ID already exists."
            )
            raise HTTPException(status_code=409, detail=detail) from exc

    return Document(**row._mapping)


@app.get("/documents/{document_id}", response_model=Document)
def get_document(document_id: int) -> Document:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, title, text, youtube_video_id, created_at
                FROM documents
                WHERE id = :id
                """
            ),
            {"id": document_id},
        ).one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    return Document(**row._mapping)


class DocumentTextUpdate(BaseModel):
    text: str = Field(min_length=1)


@app.patch("/documents/{document_id}", response_model=Document)
def update_document_text(document_id: int, body: DocumentTextUpdate) -> Document:
    """Editing the lyrics invalidates every token derived from the old text
    — furigana, gloss links, conflicts, all of it no longer corresponds to
    anything real. No version history is kept (not asked for), so this just
    deletes them outright; they're regenerated from scratch (same as a
    never-before-processed document) the next time tokens are requested.
    The shared gloss_lookups cache is untouched — it's keyed by word, not
    by document, so other documents' (and this one's next processing
    pass's) cached lookups stay valid."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                UPDATE documents SET text = :text WHERE id = :id
                RETURNING id, title, text, youtube_video_id, created_at
                """
            ),
            {"id": document_id, "text": body.text},
        ).one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail="Document not found.")

        conn.execute(
            text(
                """
                DELETE FROM conflicts
                WHERE token_id IN (SELECT id FROM tokens WHERE document_id = :id)
                """
            ),
            {"id": document_id},
        )
        conn.execute(text("DELETE FROM tokens WHERE document_id = :id"), {"id": document_id})

    return Document(**row._mapping)


SortField = Literal["id", "title", "youtube_video_id", "created_at"]


class DocumentListItem(BaseModel):
    id: int
    title: str
    youtube_video_id: Optional[str]
    created_at: datetime


class DocumentPage(BaseModel):
    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


@app.get("/documents", response_model=DocumentPage)
def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: SortField = "created_at",
    sort_dir: Literal["asc", "desc"] = "desc",
) -> DocumentPage:
    direction = "ASC" if sort_dir == "asc" else "DESC"
    offset = (page - 1) * page_size

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT id, title, youtube_video_id, created_at,
                       COUNT(*) OVER() AS total
                FROM documents
                ORDER BY {sort_by} {direction}, id {direction}
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": page_size, "offset": offset},
        ).all()

    total = rows[0].total if rows else 0
    items = [
        DocumentListItem(
            id=row.id,
            title=row.title,
            youtube_video_id=row.youtube_video_id,
            created_at=row.created_at,
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


@app.get("/jmdict/search", response_model=list[JmdictEntry])
def jmdict_search(
    q: str = Query(min_length=1),
    max_results_per_tier: int = Query(default=3, ge=1, le=20),
) -> list[JmdictEntry]:
    return [JmdictEntry(**entry) for entry in search_jmdict(q, max_results_per_tier=max_results_per_tier)]


class GlossSense(JmdictSense):
    entry_idseq: int


class GlossPiece(BaseModel):
    surface: str
    reading: str
    senses: list[GlossSense]
    ambiguous_readings: list[str]


class Gloss(BaseModel):
    reading: str
    senses: list[GlossSense]
    source: str
    pieces: list[GlossPiece] = []


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
    dictionary_form_note: Optional[str]
    normalized_form: str
    reading_katakana: str
    part_of_speech: list[str]
    is_oov: bool
    furigana_spans: list[dict]
    needs_review: bool
    review_reason: Optional[str]
    furigana_override: Optional[list[dict]]
    is_english: bool
    gloss: Optional[Gloss]
    conflicts: list[Conflict]
    start_time: Optional[Decimal]
    end_time: Optional[Decimal]


def _fetch_tokens(conn, document_id: int, token_id: Optional[int] = None) -> list[Token]:
    token_filter = "AND t.id = :token_id" if token_id is not None else ""
    rows = conn.execute(
        text(
            f"""
            SELECT t.id, t.document_id, t.position, t.char_begin, t.char_end, t.surface,
                   t.dictionary_form, t.normalized_form, t.reading_katakana,
                   t.part_of_speech, t.is_oov, t.furigana_spans, t.needs_review,
                   t.review_reason, t.furigana_override, t.start_time, t.end_time,
                   gl.reading AS gloss_reading, gl.entries AS gloss_entries, gl.source AS gloss_source
            FROM tokens t
            LEFT JOIN gloss_lookups gl ON gl.id = t.gloss_lookup_id
            WHERE t.document_id = :document_id {token_filter}
            ORDER BY t.position
            """
        ),
        {"document_id": document_id, "token_id": token_id},
    ).all()
    if not rows:
        return []

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
        {"document_id": document_id, "token_id": token_id},
    ).all()
    conflicts_by_token: dict[int, list[Conflict]] = {}
    for c in conflict_rows:
        conflicts_by_token.setdefault(c.token_id, []).append(
            Conflict(id=c.id, kind=c.kind, value=c.value, selected=c.selected)
        )

    tokens = []
    for row in rows:
        data = dict(row._mapping)
        gloss_reading = data.pop("gloss_reading")
        gloss_entries = data.pop("gloss_entries")
        gloss_source = data.pop("gloss_source")
        if gloss_reading is None:
            data["gloss"] = None
        elif gloss_source == "composite":
            # Pieces were already ranked (using each piece's own
            # part-of-speech) when the composite was built, so no
            # re-ranking needed here the way the flat jmdict case needs.
            data["gloss"] = Gloss(
                reading=gloss_reading,
                senses=[],
                source=gloss_source,
                pieces=[GlossPiece(**piece) for piece in gloss_entries["pieces"]],
            )
        else:
            data["gloss"] = Gloss(
                reading=gloss_reading,
                senses=rank_senses(gloss_entries, data["part_of_speech"][0]),
                source=gloss_source,
            )
        data["conflicts"] = conflicts_by_token.get(data["id"], [])
        data["is_english"] = is_probably_english(data["surface"])
        data["dictionary_form_reading"] = mixed_reading(data["dictionary_form"])
        data["dictionary_form_note"] = dictionary_form_note(
            data["dictionary_form"], data["normalized_form"], data["part_of_speech"][4]
        )
        tokens.append(Token(**data))
    return tokens


def _fetch_token(conn, document_id: int, token_id: int) -> Token:
    """A single token, scoped by id — for the resolve/correct endpoints,
    which only ever need to return the one token they just mutated. Avoids
    re-fetching and re-ranking every other token in the document just to
    pick one row back out."""
    return _fetch_tokens(conn, document_id, token_id=token_id)[0]


@dataclasses.dataclass
class _ProcessedDocument:
    records: list[TokenRecord]
    gloss_plan: GlossPlan


def _process_document(document_text: str) -> _ProcessedDocument:
    """Tokenize a document and resolve its glosses against the cache — the
    slow part of first processing — without writing anything."""
    records = tokenize_document(document_text)
    # A token's dictionary_form is the alternate spelling for its key.
    requests = ((key, record.dictionary_form) for record in records if (key := gloss_key(record)) is not None)
    # Autocommit, so no transaction is held open through the dictionary
    # lookups.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        return _ProcessedDocument(records, plan_glosses(conn, requests))


def _write_processed_document(conn, document_id: int, processed: _ProcessedDocument) -> None:
    """Insert a processed document's new gloss rows, its tokens (already
    linked to their glosses), and its conflicts, one statement each."""
    gloss_ids = store_glosses(conn, processed.gloss_plan)
    rows = []
    for record in processed.records:
        key = gloss_key(record)
        rows.append(
            {
                # Not dataclasses.asdict, which would deep-copy every field,
                # conflict_options included, only to discard it.
                **{f.name: getattr(record, f.name) for f in dataclasses.fields(record) if f.name != "conflict_options"},
                "gloss_lookup_id": gloss_ids[key] if key is not None else None,
            }
        )
    conn.execute(
        text(
            """
            INSERT INTO tokens (
                document_id, position, char_begin, char_end, surface,
                dictionary_form, normalized_form, reading_katakana,
                part_of_speech, is_oov, furigana_spans, needs_review,
                review_reason, gloss_lookup_id
            )
            SELECT :document_id, position, char_begin, char_end, surface,
                   dictionary_form, normalized_form, reading_katakana,
                   part_of_speech, is_oov, furigana_spans, needs_review,
                   review_reason, gloss_lookup_id
            FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS r(
                position int, char_begin int, char_end int, surface text,
                dictionary_form text, normalized_form text, reading_katakana text,
                part_of_speech jsonb, is_oov boolean, furigana_spans jsonb,
                needs_review boolean, review_reason text, gloss_lookup_id int
            )
            ORDER BY position
            """
        ),
        {"document_id": document_id, "rows": json.dumps(rows)},
    )
    create_conflicts(conn, document_id, processed.records)


@app.get("/documents/{document_id}/tokens", response_model=list[Token])
def get_document_tokens(document_id: int) -> list[Token]:
    while True:
        with engine.connect() as conn:
            existing = _fetch_tokens(conn, document_id)
            if not existing:
                # Tokens only exist for a document that does, so the document
                # is only read (and checked for) when there are none.
                document_text = conn.execute(
                    text("SELECT text FROM documents WHERE id = :id"),
                    {"id": document_id},
                ).scalar_one_or_none()

        if existing:
            if all(t.gloss is not None or not is_glossable(t.part_of_speech, bool(t.conflicts)) for t in existing):
                return existing
            # Tokens missing their gloss link: tokenized before gloss support
            # existed, or unlinked by a migration that reset the gloss cache
            # (as 0005 did).
            with engine.begin() as conn:
                attach_glosses(conn, document_id)
                return _fetch_tokens(conn, document_id)

        if document_text is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        processed = _process_document(document_text)
        if not processed.records:
            return []

        with engine.begin() as conn:
            # Locks the document, so a concurrent first request or text edit
            # waits for this write instead of racing it.
            current_text = conn.execute(
                text("SELECT text FROM documents WHERE id = :id FOR UPDATE"),
                {"id": document_id},
            ).scalar_one_or_none()

            if current_text is None:
                raise HTTPException(status_code=404, detail="Document not found.")
            # Its own statement, not part of the locking one: under READ
            # COMMITTED, only a statement started after the lock was granted
            # sees tokens that the lock's previous holder committed.
            already_processed = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM tokens WHERE document_id = :id)"),
                {"id": document_id},
            ).scalar_one()
            if already_processed:
                return _fetch_tokens(conn, document_id)
            if current_text == document_text:
                _write_processed_document(conn, document_id, processed)
                return _fetch_tokens(conn, document_id)
        # The text was edited while this was processing: start over on the
        # new text.


class ConflictResolution(BaseModel):
    conflict_id: int


@app.post("/documents/{document_id}/tokens/{token_id}/resolve", response_model=Token)
def resolve_token_conflict(document_id: int, token_id: int, body: ConflictResolution) -> Token:
    with engine.begin() as conn:
        try:
            resolve_conflict(conn, document_id, token_id, body.conflict_id)
        except ConflictNotFound:
            raise HTTPException(status_code=404, detail="Conflict option not found for this token.")

        return _fetch_token(conn, document_id, token_id)


_KANA_ONLY_RE = re.compile(r"^[ぁ-んァ-ヶー]+$")


class ReadingCorrection(BaseModel):
    reading: str = Field(min_length=1)

    @field_validator("reading")
    @classmethod
    def kana_only(cls, value: str) -> str:
        if not _KANA_ONLY_RE.match(value):
            raise ValueError("Reading must be hiragana and/or katakana only.")
        return value


@app.post("/documents/{document_id}/tokens/{token_id}/correct", response_model=Token)
def correct_token_reading(document_id: int, token_id: int, body: ReadingCorrection) -> Token:
    with engine.begin() as conn:
        try:
            correct_reading(conn, document_id, token_id, body.reading)
        except TokenNotFound:
            raise HTTPException(status_code=404, detail="Token not found for this document.")

        return _fetch_token(conn, document_id, token_id)
