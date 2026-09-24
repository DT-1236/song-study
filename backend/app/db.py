import json
import os

from sqlalchemy import create_engine, text

from app.env import load_env

load_env()

engine = create_engine(os.environ["DATABASE_URL"])


def json_param(value) -> str | None:
    """`value` as JSON text for a JSONB parameter, with None kept as SQL
    NULL rather than turned into a JSON null."""
    return None if value is None else json.dumps(value)


def _owned_document_row(conn, id: int, user_id: int, for_update: bool = False):
    """The row of the user's document; None if they have no such document."""
    query = "SELECT id, title, text, youtube_video_id, lrclib_uri, lrclib_replaces_text, lrclib_lines, CASE WHEN edited_lines_text = text THEN edited_lines END AS edited_lines, created_at FROM documents WHERE id = :id AND owner_id = :owner_id"
    if for_update:
        query += " FOR UPDATE"
    return conn.execute(
        text(query),
        {"id": id, "owner_id": user_id},
    ).one_or_none()
