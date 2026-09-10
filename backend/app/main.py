import dataclasses
import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import engine
from app.glosses import search_jmdict
from app.tokenization import tokenize_document

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


class Token(BaseModel):
    id: int
    document_id: int
    position: int
    char_begin: int
    char_end: int
    surface: str
    dictionary_form: str
    normalized_form: str
    reading_katakana: str
    part_of_speech: list[str]
    is_oov: bool
    furigana_spans: list[dict]
    needs_review: bool
    review_reason: Optional[str]
    furigana_override: Optional[list[dict]]
    start_time: Optional[Decimal]
    end_time: Optional[Decimal]


def _fetch_tokens(conn, document_id: int) -> list[Token]:
    rows = conn.execute(
        text(
            """
            SELECT id, document_id, position, char_begin, char_end, surface,
                   dictionary_form, normalized_form, reading_katakana,
                   part_of_speech, is_oov, furigana_spans, needs_review,
                   review_reason, furigana_override, start_time, end_time
            FROM tokens
            WHERE document_id = :document_id
            ORDER BY position
            """
        ),
        {"document_id": document_id},
    ).all()
    return [Token(**row._mapping) for row in rows]


@app.get("/documents/{document_id}/tokens", response_model=list[Token])
def get_document_tokens(document_id: int) -> list[Token]:
    with engine.begin() as conn:
        doc_row = conn.execute(
            text("SELECT text FROM documents WHERE id = :id"),
            {"id": document_id},
        ).one_or_none()

        if doc_row is None:
            raise HTTPException(status_code=404, detail="Document not found.")

        existing = _fetch_tokens(conn, document_id)
        if existing:
            return existing

        records = tokenize_document(doc_row.text)
        if not records:
            return []

        conn.execute(
            text(
                """
                INSERT INTO tokens (
                    document_id, position, char_begin, char_end, surface,
                    dictionary_form, normalized_form, reading_katakana,
                    part_of_speech, is_oov, furigana_spans, needs_review,
                    review_reason
                ) VALUES (
                    :document_id, :position, :char_begin, :char_end, :surface,
                    :dictionary_form, :normalized_form, :reading_katakana,
                    CAST(:part_of_speech AS JSONB), :is_oov,
                    CAST(:furigana_spans AS JSONB), :needs_review, :review_reason
                )
                """
            ),
            [
                {
                    "document_id": document_id,
                    **{
                        k: json.dumps(v) if k in ("part_of_speech", "furigana_spans") else v
                        for k, v in dataclasses.asdict(r).items()
                    },
                }
                for r in records
            ],
        )

        return _fetch_tokens(conn, document_id)
