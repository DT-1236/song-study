import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import engine

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
            raise HTTPException(
                status_code=409,
                detail="A document with this YouTube video ID already exists.",
            ) from exc

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
