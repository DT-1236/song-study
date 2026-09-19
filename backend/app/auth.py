"""Logging in with Google. The browser is sent to Google and back to
/auth/callback, which finds or creates the user for the Google account and
records them in the session cookie."""

import os
import secrets

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.db import engine
from app.users import current_user_id

router = APIRouter(prefix="/auth")

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def session_secret() -> str:
    """SESSION_SECRET, or a random one — which logs everyone out on every
    restart — while it isn't set."""
    return os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32)


def upsert_google_user(conn, sub: str, email: str | None, name: str) -> int:
    """The id of the user for the Google account `sub`, created if this is
    their first login; their email and name are refreshed from Google."""
    return conn.execute(
        text(
            """
            INSERT INTO users (google_sub, email, name)
            VALUES (:sub, :email, :name)
            ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email, name = EXCLUDED.name
            RETURNING id
            """
        ),
        {"sub": sub, "email": email, "name": name},
    ).scalar_one()


@router.get("/login")
async def login(request: Request):
    """Send the browser to Google to log in."""
    if not os.environ.get("GOOGLE_CLIENT_ID"):
        raise HTTPException(status_code=503, detail="Google login isn't configured (GOOGLE_CLIENT_ID).")
    return await oauth.google.authorize_redirect(request, str(request.url_for("auth_callback")))


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    """Finish a Google login: log the account in and return to the app."""
    token = await oauth.google.authorize_access_token(request)
    info = token["userinfo"]
    with engine.begin() as conn:
        user_id = upsert_google_user(conn, info["sub"], info.get("email"), info.get("name") or info.get("email") or "")
    request.session.clear()
    request.session["user_id"] = user_id
    return RedirectResponse(FRONTEND_URL)


class Me(BaseModel):
    id: int
    name: str
    email: str | None


@router.get("/me", response_model=Me)
def me(user_id: int = Depends(current_user_id)) -> Me:
    """The logged-in user."""
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, name, email FROM users WHERE id = :id"), {"id": user_id}).one_or_none()
    if row is None:
        # A session for a user who's since been deleted.
        raise HTTPException(status_code=401, detail="Log in to continue.")
    return Me(**row._mapping)


@router.post("/logout", status_code=204)
def logout(request: Request) -> None:
    """Log the browser out."""
    request.session.clear()
