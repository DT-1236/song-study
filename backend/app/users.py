"""Who a request acts as: the user its session cookie says logged in (see
app/auth.py), and which documents that lets it reach."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text

from app.db import engine


def current_user_id(request: Request) -> int:
    """The id of the user making the request; a 401 if they aren't logged in."""
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Log in to continue.")
    return user_id


CurrentUser = Annotated[int, Depends(current_user_id)]


def document_is_owned(conn, document_id: int, user_id: int) -> bool:
    """Whether the document exists and belongs to the user."""
    return conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM documents WHERE id = :id AND owner_id = :owner_id)"
        ),
        {"id": document_id, "owner_id": user_id},
    ).scalar_one()


def owned_document_id(document_id: int, user_id: CurrentUser) -> int:
    """The path's document id, once the document is known to belong to the
    logged-in user; a 404 otherwise, since one user must not learn which of
    another's documents exist. Routes keyed by document id take it as
    OwnedDocument rather than int, so the check is part of the signature and
    can't be left out of a new one."""
    # Its own connection, before the route opens its transaction: a document
    # can't change hands (nothing transfers or deletes one), and the routes
    # that go on to write still re-scope by owner_id under their own lock.
    with engine.connect() as conn:
        owned = document_is_owned(conn, document_id, user_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document_id


OwnedDocument = Annotated[int, Depends(owned_document_id)]
