"""Documents belong to a user, and every route acts only on the caller's."""

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.main import DocumentCreate, DocumentTextUpdate
from app.users import owned_document_id
from tests.support import (
    TEST_USER_ID,
    api_routes,
    as_user,
    create_document,
    get_document,
    list_documents,
    update_document_text,
)


def test_documents_are_created_for_the_calling_user(committed_engine, other_user):
    mine = create_document(DocumentCreate(title="mine", text="あ"))
    with as_user(other_user):
        theirs = create_document(DocumentCreate(title="theirs", text="い"))

    with committed_engine.connect() as conn:
        owners = dict(conn.execute(text("SELECT id, owner_id FROM documents")).all())
    assert owners == {mine.id: TEST_USER_ID, theirs.id: other_user}


def test_a_user_only_lists_their_own_documents(committed_engine, other_user):
    mine = create_document(DocumentCreate(title="mine", text="あ"))
    with as_user(other_user):
        theirs = create_document(DocumentCreate(title="theirs", text="い"))

    def listed():
        return list_documents(page=1, page_size=20, sort_by="id", sort_dir="asc")

    assert [d.id for d in listed().items] == [mine.id]
    with as_user(other_user):
        assert [d.id for d in listed().items] == [theirs.id]
        assert listed().total == 1


def test_routes_treat_another_users_document_as_missing(committed_engine, other_user):
    with as_user(other_user):
        theirs = create_document(DocumentCreate(title="theirs", text="い"))

    # A read and a write: that every other route keyed by a document is scoped
    # the same way is test_every_route_keyed_by_a_document_is_owner_scoped's.
    for call in (
        lambda: get_document(theirs.id),
        lambda: update_document_text(theirs.id, DocumentTextUpdate(text="う")),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404

    with as_user(other_user):
        assert get_document(theirs.id).text == "い"


def test_a_youtube_video_can_be_used_once_per_user(committed_engine, other_user):
    create_document(DocumentCreate(title="a", text="あ", youtube_video_id="vid"))
    with as_user(other_user):
        create_document(DocumentCreate(title="b", text="い", youtube_video_id="vid"))

    with pytest.raises(HTTPException) as exc:
        create_document(DocumentCreate(title="c", text="う", youtube_video_id="vid"))
    assert exc.value.status_code == 409
    assert '"a"' in exc.value.detail


def _dependency_calls(dependant):
    """Every function `dependant` resolves, its sub-dependencies included."""
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _dependency_calls(sub)


def test_every_route_keyed_by_a_document_is_owner_scoped():
    """A route that takes a document id from its path must take it as
    OwnedDocument, so ownership can't be left to the route's own SQL to
    remember."""
    unscoped = [
        route.path
        for route in api_routes()
        if "{document_id}" in route.path
        and owned_document_id not in set(_dependency_calls(route.dependant))
    ]

    assert unscoped == []
