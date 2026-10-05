"""Logging in with Google: users are found by their Google account, and a
request acts as whoever its session says logged in."""

import types

import pytest
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import auth, main
from app.auth import me, upsert_google_user
from app.users import current_user_id
from tests.support import as_session_user


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

    assert me(user_id).email == "me@example.com"
    with pytest.raises(HTTPException) as exc:
        me(user_id + 1000)
    assert exc.value.status_code == 401


@pytest.fixture
def browser():
    """A client with a cookie jar of its own, whose requests act as whoever
    their session says rather than as the test user. https, so the session
    cookie comes back whether or not it's marked Secure."""
    with as_session_user():
        yield TestClient(main.app, base_url="https://testserver")


@pytest.fixture
def google(monkeypatch, committed_engine):
    """Google, standing in for the token exchange at the end of a login: it
    vouches for whichever account the returned dict is set to. Logging in
    commits a user, hence `committed_engine`."""
    account = {"sub": "sub-callback", "email": "cb@example.com", "name": "CB"}

    async def authorize_access_token(request):
        return {"userinfo": account}

    monkeypatch.setattr(
        auth.oauth.google, "authorize_access_token", authorize_access_token
    )
    return account


def test_returning_from_google_logs_the_account_in(browser, google):
    response = browser.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == auth.APP_URL
    assert browser.get("/api/auth/me").json()["email"] == "cb@example.com"


def test_logging_out_ends_the_session(browser, google):
    browser.get("/api/auth/callback", follow_redirects=False)

    assert browser.post("/api/auth/logout").status_code == 204
    assert browser.get("/api/auth/me").status_code == 401


def test_logging_in_replaces_whoever_the_session_had(browser, google):
    browser.get("/api/auth/callback", follow_redirects=False)
    google.update(sub="sub-callback-2", email="cb2@example.com")

    browser.get("/api/auth/callback", follow_redirects=False)

    assert browser.get("/api/auth/me").json()["email"] == "cb2@example.com"


def test_logging_in_is_refused_until_google_is_configured(browser, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)

    assert browser.get("/api/auth/login").status_code == 503


def test_logging_in_sends_google_the_callback_route(browser, monkeypatch):
    # The address Google returns the browser to, which must also be
    # registered in the Google Cloud console.
    sent = []

    async def authorize_redirect(request, redirect_uri):
        sent.append(redirect_uri)
        return RedirectResponse("https://accounts.google.com/")

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(auth.oauth.google, "authorize_redirect", authorize_redirect)

    browser.get("/api/auth/login", follow_redirects=False)

    # Served, as test_returning_from_google_logs_the_account_in shows.
    assert sent == [f"{auth.APP_URL}/api/auth/callback"]
