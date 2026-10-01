"""Gmail, through the Google account the protected person connected via Clerk.

Clerk holds the Google OAuth token. The server asks Clerk for it on each call,
so Scam Stop never stores a Google password or refresh token of its own.
The caregiver's own mailbox is never read. With the person's permission
(`gmail.modify` and `gmail.settings.basic`) Scam Stop also moves scam emails to
the Bin and keeps filters that send a scammer's later mail there.
"""
import base64
import os
from collections.abc import Iterator

import httpx
from clerk_backend_api import Clerk
from fastapi import HTTPException

from domain.tools import MailboxError

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"           # move mail to the Bin and back; also allows reading
SETTINGS_SCOPE = "https://www.googleapis.com/auth/gmail.settings.basic"  # create and delete filters
BIN_SCOPES = {MODIFY_SCOPE, SETTINGS_SCOPE}
REVOKE = "https://oauth2.googleapis.com/revoke"
MAX_PAGES = 10  # 50 emails a page, so one scan looks at up to 500


def google_grant(user_id: str) -> tuple[str, set[str]]:
    """The user's Google access token from Clerk, and the scopes it carries. Clerk refreshes it when it has expired."""
    with Clerk(bearer_auth=os.environ["CLERK_SECRET_KEY"]) as clerk:
        tokens = clerk.users.get_o_auth_access_token(user_id=user_id, provider="oauth_google")
    token = next((item for item in tokens if item.token), None)
    if token is None:
        raise HTTPException(403, "No Google account is connected. Sign in with Google.")
    scopes = set(token.scopes or [])
    if not scopes & {READ_SCOPE, MODIFY_SCOPE}:
        raise HTTPException(403, "Google is connected without Gmail read access. Sign in with Google again to grant it.")
    return token.token, scopes


def google_token(user_id: str) -> str:
    """The user's Google access token, checked for Gmail read access."""
    return google_grant(user_id)[0]


def gmail_get(token: str, path: str, params: dict | list | None = None) -> dict:
    return gmail_call("GET", token, path, params=params)


def gmail_call(method: str, token: str, path: str, params: dict | list | None = None, body: dict | None = None) -> dict:
    response = httpx.request(method, f"{GMAIL}{path}", params=params, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if response.status_code == 401:
        raise HTTPException(401, "Google refused the token. Sign in with Google again.")
    if response.status_code == 403:
        raise HTTPException(403, "Google refused access to the mailbox.")
    if response.status_code == 404:
        raise HTTPException(404, "Email not found")
    if response.is_error:
        raise HTTPException(502, f"Gmail answered {response.status_code}")
    return response.json() if response.content else {}  # a filter deletion answers with an empty body


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


def _gone(error: Exception) -> bool:
    """Gmail no longer has the email or filter: the person deleted it, so there is nothing left to do."""
    return isinstance(error.__cause__, HTTPException) and error.__cause__.status_code == 404


class GmailMailbox:
    """The domain tools' `Mailbox`, for real: each call finds the mailbox's owner and uses their Google token.

    Errors become `MailboxError` in plain words, so a tool can say what went wrong without knowing about HTTP.
    """

    def __init__(self, store):
        self.store = store

    def _token(self, mailbox_id: str) -> str:
        mailbox = self.store.mailbox(mailbox_id)
        if mailbox is None or mailbox["kind"] != "gmail" or mailbox["status"] == "disconnected":
            raise MailboxError("the mailbox is no longer connected")
        try:
            token, scopes = google_grant(mailbox["owner_user_id"])
        except HTTPException as error:
            raise MailboxError(str(error.detail)) from error
        if not BIN_SCOPES <= scopes:
            raise MailboxError("Gmail is connected without permission to move mail to the Bin; send a new invite link so it can be granted")
        return token

    def _call(self, mailbox_id: str, method: str, path: str, **kwargs) -> dict:
        token = self._token(mailbox_id)
        try:
            return gmail_call(method, token, path, **kwargs)
        except HTTPException as error:
            raise MailboxError(str(error.detail)) from error

    def trash(self, mailbox_id: str, message_ids: list[str]) -> list[str]:
        moved = []
        for message_id in message_ids:
            try:
                self._call(mailbox_id, "POST", f"/messages/{message_id}/trash")
                moved.append(message_id)
            except MailboxError as error:
                if not _gone(error):
                    raise
        return moved

    def untrash(self, mailbox_id: str, message_ids: list[str]) -> None:
        for message_id in message_ids:
            try:
                self._call(mailbox_id, "POST", f"/messages/{message_id}/untrash")
            except MailboxError as error:
                if not _gone(error):  # emptied from the Bin since: it cannot come back
                    raise

    def find_from(self, mailbox_id: str, sender: str) -> list[str]:
        token = self._token(mailbox_id)
        try:
            return list(message_ids(token, f"from:({sender})"))  # the Bin and Spam are left out by Gmail
        except HTTPException as error:
            raise MailboxError(str(error.detail)) from error

    def add_filter(self, mailbox_id: str, sender: str) -> tuple[str, bool]:
        """Reuse a filter that already bins this sender, so undoing never removes one the person made."""
        for item in self._call(mailbox_id, "GET", "/settings/filters").get("filter", []):
            if item.get("criteria", {}).get("from", "").lower() == sender and "TRASH" in item.get("action", {}).get("addLabelIds", []):
                return item["id"], False
        made = self._call(mailbox_id, "POST", "/settings/filters", body={"criteria": {"from": sender}, "action": {"addLabelIds": ["TRASH"]}})
        return made["id"], True

    def remove_filter(self, mailbox_id: str, filter_id: str) -> None:
        try:
            self._call(mailbox_id, "DELETE", f"/settings/filters/{filter_id}")
        except MailboxError as error:
            if not _gone(error):  # the person removed it already
                raise
