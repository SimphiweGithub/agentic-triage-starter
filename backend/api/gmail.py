"""Gmail, read through the Google account the user signed in with via Clerk.

Clerk holds the Google OAuth token. The server asks Clerk for it on each call,
so KinGuard never stores a Google password or refresh token of its own.
"""
import base64
from datetime import datetime, timezone
import html
import os
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import httpx
from clerk_backend_api import Clerk
from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from api.routes import Withheld, take_in_email
from domain.schemas import DecisionRecord

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

router = APIRouter(prefix="/gmail", tags=["gmail"])


class GmailMessage(BaseModel):
    id: str
    thread_id: str
    sender: str = ""
    subject: str = ""
    date: str = ""
    snippet: str = ""


def signed_in_user(request: Request) -> str:
    """The Clerk user id behind the request's session token, or 401."""
    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret:
        raise HTTPException(503, "Sign-in is not configured: set CLERK_SECRET_KEY in .env")
    parties = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
    state = authenticate_request(request, AuthenticateRequestOptions(secret_key=secret, authorized_parties=parties or None))
    if not state.is_signed_in or not state.payload:
        raise HTTPException(401, "Sign in first")
    return state.payload["sub"]


def google_token(user_id: str) -> str:
    """The user's Google access token from Clerk. Clerk refreshes it when it has expired."""
    with Clerk(bearer_auth=os.environ["CLERK_SECRET_KEY"]) as clerk:
        tokens = clerk.users.get_o_auth_access_token(user_id=user_id, provider="oauth_google")
    token = next((item for item in tokens if item.token), None)
    if token is None:
        raise HTTPException(403, "No Google account is connected. Sign in with Google.")
    if READ_SCOPE not in (token.scopes or []):
        raise HTTPException(403, "Google is connected without Gmail read access. Sign in with Google again to grant it.")
    return token.token


def gmail_get(token: str, path: str, params: dict | list | None = None) -> dict:
    response = httpx.get(f"{GMAIL}{path}", params=params, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if response.status_code == 401:
        raise HTTPException(401, "Google refused the token. Sign in with Google again.")
    if response.status_code == 404:
        raise HTTPException(404, "Email not found")
    if response.is_error:
        raise HTTPException(502, f"Gmail answered {response.status_code}")
    return response.json()


def _summary(message: dict) -> GmailMessage:
    headers = {item["name"].lower(): item["value"] for item in message.get("payload", {}).get("headers", [])}
    return GmailMessage(id=message["id"], thread_id=message["threadId"], sender=headers.get("from", ""),
                        subject=headers.get("subject", ""), date=headers.get("date", ""), snippet=html.unescape(message.get("snippet", "")))


@router.get("/messages", response_model=list[GmailMessage])
def messages(user_id: str = Depends(signed_in_user), max_results: int = Query(10, ge=1, le=50),
             q: str = Query("in:inbox", description="A Gmail search, for example is:unread")):
    """The newest emails in the signed-in user's Gmail, newest first. Read only."""
    token = google_token(user_id)
    found = gmail_get(token, "/messages", {"maxResults": max_results, "q": q}).get("messages", [])
    headers = [("format", "metadata")] + [("metadataHeaders", name) for name in ("From", "Subject", "Date")]
    with ThreadPoolExecutor(max_workers=8) as pool:  # one call per email, so fetch them side by side
        return list(pool.map(lambda item: _summary(gmail_get(token, f"/messages/{item['id']}", headers)), found))


@router.post("/messages/{message_id}/intake", response_model=DecisionRecord | Withheld)
def intake(message_id: str, user_id: str = Depends(signed_in_user)):
    """Hand one Gmail email to the engine, exactly as if it had been forwarded as .eml text."""
    raw = gmail_get(google_token(user_id), f"/messages/{message_id}", {"format": "raw"})["raw"]
    return take_in_email(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace"))


# ---- watching: check the signed-in user's inbox on a timer, so nobody has to click ----

WATCH = {"user_id": None, "thread": None, "seen": set(), "last_check": None, "last_error": None, "taken_in": 0}


def check_new_mail(user_id: str, limit: int = 10) -> int:
    """Take in each inbox email from the last two days that has not been checked yet, oldest first."""
    token = google_token(user_id)
    found = gmail_get(token, "/messages", {"maxResults": limit, "q": "in:inbox newer_than:2d"}).get("messages", [])
    new = [item["id"] for item in reversed(found) if item["id"] not in WATCH["seen"]]
    for message_id in new:
        raw = gmail_get(token, f"/messages/{message_id}", {"format": "raw"})["raw"]
        take_in_email(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace"))
        WATCH["seen"].add(message_id)  # after a restart this starts empty; re-checking an email returns its earlier decision
    return len(new)


def start_watching(user_id: str) -> None:
    """Watch this user's inbox every GMAIL_WATCH_SECONDS (default 60). One watcher at a time."""
    WATCH["user_id"] = user_id
    if WATCH["thread"] is not None and WATCH["thread"].is_alive():
        return
    seconds = float(os.getenv("GMAIL_WATCH_SECONDS", "60"))

    def loop() -> None:
        while WATCH["user_id"]:
            try:
                WATCH["taken_in"] += check_new_mail(WATCH["user_id"])
                WATCH["last_error"] = None
            except Exception as error:  # a Gmail or Clerk problem must never stop the server
                WATCH["last_error"] = f"{type(error).__name__}: {getattr(error, 'detail', error)}"
            WATCH["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            time.sleep(seconds)

    WATCH["thread"] = threading.Thread(target=loop, daemon=True, name="gmail-watch")
    WATCH["thread"].start()


def watch_status() -> dict:
    return {"watching": bool(WATCH["user_id"]), "last_check": WATCH["last_check"], "last_error": WATCH["last_error"],
            "taken_in": WATCH["taken_in"]}


@router.post("/watch")
def watch(user_id: str = Depends(signed_in_user)):
    """Start checking the signed-in user's inbox automatically."""
    start_watching(user_id)
    return watch_status()


@router.get("/watch")
def watch_state():
    """Whether the inbox is being watched, when it was last checked, and the last error if any."""
    return watch_status()


@router.delete("/watch")
def stop_watching():
    """Stop checking the inbox. The loop ends after its current wait."""
    WATCH["user_id"] = None
    return watch_status()
