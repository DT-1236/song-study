"""Documents belong to a user, and every route acts only on the caller's."""

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from tests.support import TEST_USER_ID
from app.main import (
    DocumentCreate,
    DocumentTextUpdate,
    create_document,
    get_alternate_readings,
    get_document,
    get_document_tokens,
    list_documents,
    unlink_lrclib,
    update_document_text,
)


@pytest.fixture
def other_user(committed_engine):
    with committed_engine.begin() as conn:
        user_id = conn.execute(text("INSERT INTO users (name) VALUES ('other') RETURNING id")).scalar_one()
    yield user_id
    with committed_engine.begin() as conn:
        conn.execute(text("DELETE FROM documents WHERE owner_id = :id"), {"id": user_id})
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def test_documents_are_created_for_the_calling_user(committed_engine, other_user):
    mine = create_document(DocumentCreate(title="mine", text="あ"), user_id=TEST_USER_ID)
    theirs = create_document(DocumentCreate(title="theirs", text="い"), user_id=other_user)

    with committed_engine.connect() as conn:
        owners = dict(conn.execute(text("SELECT id, owner_id FROM documents")).all())
    assert owners == {mine.id: TEST_USER_ID, theirs.id: other_user}


def test_a_user_only_lists_their_own_documents(committed_engine, other_user):
    mine = create_document(DocumentCreate(title="mine", text="あ"), user_id=TEST_USER_ID)
    theirs = create_document(DocumentCreate(title="theirs", text="い"), user_id=other_user)

    assert [d.id for d in list_documents(user_id=TEST_USER_ID, page=1, page_size=20, sort_by="id", sort_dir="asc").items] == [mine.id]
    assert [d.id for d in list_documents(page=1, page_size=20, sort_by="id", sort_dir="asc", user_id=other_user).items] == [theirs.id]
    assert list_documents(page=1, page_size=20, sort_by="id", sort_dir="asc", user_id=other_user).total == 1


def test_routes_treat_another_users_document_as_missing(committed_engine, other_user):
    theirs = create_document(DocumentCreate(title="theirs", text="い"), user_id=other_user)

    for call in (
        lambda: get_document(theirs.id, user_id=TEST_USER_ID),
        lambda: get_document_tokens(theirs.id, user_id=TEST_USER_ID),
        lambda: get_alternate_readings(theirs.id, 1, user_id=TEST_USER_ID),
        lambda: unlink_lrclib(theirs.id, user_id=TEST_USER_ID),
        lambda: update_document_text(theirs.id, DocumentTextUpdate(text="う"), user_id=TEST_USER_ID),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404

    assert get_document(theirs.id, user_id=other_user).text == "い"


def test_a_youtube_video_can_be_used_once_per_user(committed_engine, other_user):
    create_document(DocumentCreate(title="a", text="あ", youtube_video_id="vid"), user_id=TEST_USER_ID)
    create_document(DocumentCreate(title="b", text="い", youtube_video_id="vid"), user_id=other_user)

    with pytest.raises(HTTPException) as exc:
        create_document(DocumentCreate(title="c", text="う", youtube_video_id="vid"), user_id=TEST_USER_ID)
    assert exc.value.status_code == 409
    assert '"a"' in exc.value.detail
