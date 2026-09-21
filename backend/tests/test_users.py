"""Documents belong to a user, and every route acts only on the caller's."""

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.main import (
    ConflictResolution,
    DocumentCreate,
    DocumentTextUpdate,
    LineTimingsUpdate,
    LrclibLink,
    PhraseAcceptance,
    ReadingCorrection,
    TokensIgnored,
    TokensReading,
)
from app.users import owned_document_id
from tests.support import (
    TEST_USER_ID,
    accept_phrase_suggestions_endpoint,
    api_routes,
    apply_tokens_reading,
    as_user,
    correct_token_reading,
    create_document,
    get_alternate_readings,
    get_document,
    get_document_tokens,
    link_lrclib,
    list_documents,
    resolve_phrase_furigana_endpoint,
    resolve_token_conflict,
    save_line_timings,
    set_tokens_ignored,
    unlink_lrclib,
    unmerge_phrase_tokens,
    update_document_text,
)


@pytest.fixture
def other_user(committed_engine):
    with committed_engine.begin() as conn:
        user_id = conn.execute(
            text("INSERT INTO users (name) VALUES ('other') RETURNING id")
        ).scalar_one()
    yield user_id
    with committed_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM documents WHERE owner_id = :id"), {"id": user_id}
        )
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


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

    for call in (
        lambda: get_document(theirs.id),
        lambda: get_document_tokens(theirs.id),
        lambda: get_alternate_readings(theirs.id, 1),
        lambda: unlink_lrclib(theirs.id),
        lambda: update_document_text(theirs.id, DocumentTextUpdate(text="う")),
        lambda: link_lrclib(theirs.id, LrclibLink(uri="lrclib:/1")),
        lambda: resolve_token_conflict(theirs.id, 1, ConflictResolution(conflict_id=1)),
        lambda: accept_phrase_suggestions_endpoint(
            theirs.id, PhraseAcceptance(conflict_ids=[1])
        ),
        lambda: resolve_phrase_furigana_endpoint(
            theirs.id, ConflictResolution(conflict_id=1)
        ),
        lambda: unmerge_phrase_tokens(theirs.id, 1),
        lambda: correct_token_reading(theirs.id, 1, ReadingCorrection(reading="あ")),
        lambda: apply_tokens_reading(
            theirs.id, TokensReading(token_ids=[1], reading="あ")
        ),
        lambda: set_tokens_ignored(
            theirs.id, TokensIgnored(token_ids=[1], ignored=True)
        ),
        lambda: save_line_timings(theirs.id, LineTimingsUpdate(text="い", lines=[])),
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
