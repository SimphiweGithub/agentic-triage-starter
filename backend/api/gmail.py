"""Gmail, read through the Google account the protected person connected via Clerk.

Clerk holds the Google OAuth token. The server asks Clerk for it on each call,
so Scam Stop never stores a Google password or refresh token of its own.
The caregiver's own mailbox is never read.
"""
import base64
import os
from collections.abc import Iterator

import httpx
from clerk_backend_api import Clerk
from fastapi import HTTPException

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
REVOKE = "https://oauth2.googleapis.com/revoke"
MAX_PAGES = 10  # 50 emails a page, so one scan looks at up to 500


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
    if response.status_code == 403:
        raise HTTPException(403, "Google refused access to the mailbox.")
    if response.status_code == 404:
        raise HTTPException(404, "Email not found")
    if response.is_error:
        raise HTTPException(502, f"Gmail answered {response.status_code}")
    return response.json()


def message_ids(token: str, query: str) -> Iterator[str]:
    """The ids of every email matching a Gmail search, newest first, page by page."""
    page = None
    for _ in range(MAX_PAGES):
        params = {"maxResults": 50, "q": query, **({"pageToken": page} if page else {})}
        found = gmail_get(token, "/messages", params)
        for item in found.get("messages", []):
            yield item["id"]
        page = found.get("nextPageToken")
        if not page:
            return


def raw_email(token: str, message_id: str) -> str:
    """One email as the raw text of an .eml file, ready for the engine."""
    raw = gmail_get(token, f"/messages/{message_id}", {"format": "raw"})["raw"]
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")


def revoke(token: str) -> None:
    """Tell Google to cancel this access. Best effort: the person can always remove it in their Google account too."""
    try:
        httpx.post(REVOKE, params={"token": token}, timeout=10)
    except httpx.HTTPError as error:
        print(f"could not revoke the Google token: {type(error).__name__}")
