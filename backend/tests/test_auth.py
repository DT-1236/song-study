"""Logging in with Google: users are found by their Google account, and a
request acts as whoever its session says logged in."""

import types

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.auth import me, upsert_google_user
from app.users import current_user_id


def request_with(session: dict):
    return types.SimpleNamespace(session=session)


def test_a_request_without_a_login_is_refused():
    with pytest.raises(HTTPException) as exc:
        current_user_id(request_with({}))
    assert exc.value.status_code == 401


def test_a_request_acts_as_the_user_in_its_session():
    assert current_user_id(request_with({"user_id": 5})) == 5


def test_first_login_creates_a_user_and_later_ones_reuse_it(db_conn):
    first = upsert_google_user(db_conn, "sub-1", "a@example.com", "A")
    again = upsert_google_user(db_conn, "sub-1", "new@example.com", "A B")
    other = upsert_google_user(db_conn, "sub-2", "b@example.com", "B")

    assert again == first
    assert other != first
    row = db_conn.execute(
        text("SELECT email, name FROM users WHERE id = :id"), {"id": first}
    ).one()
    assert (row.email, row.name) == ("new@example.com", "A B")


def test_me_returns_the_logged_in_user(committed_engine):
    with committed_engine.begin() as conn:
        user_id = upsert_google_user(conn, "sub-me", "me@example.com", "Me")
    try:
        assert me(user_id).email == "me@example.com"
        with pytest.raises(HTTPException) as exc:
            me(user_id + 1000)
        assert exc.value.status_code == 401
    finally:
        with committed_engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
