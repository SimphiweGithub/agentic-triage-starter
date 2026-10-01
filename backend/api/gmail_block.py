"""Blocking a scammer in the person's own Gmail, when the agent marks them.

The scam email is moved out of the inbox into Spam, and a Gmail filter sends every later email from that sender to
the Bin. Both can be undone, and Bin and Spam keep mail for 30 days, so nothing is destroyed. Needs the
gmail.modify and gmail.settings.basic permissions; without them the sender is still marked and the trace says so.
"""
from api import gmail
from api.store import get_store
from domain import tools
from domain.schemas import RawInputReport

NEEDS = (gmail.MODIFY_SCOPE, gmail.SETTINGS_SCOPE)


def _mailbox_owner(mailbox_id: str) -> dict | None:
    mailbox = get_store().mailbox(mailbox_id)
    if mailbox is None or mailbox["kind"] != "gmail" or mailbox["status"] == "disconnected" or not mailbox["owner_user_id"]:
        return None
    return mailbox


def block_in_gmail(target: str, report: RawInputReport) -> dict | None:
    """Move the scam email to Spam and filter the sender's future emails to the Bin. None for anything not from Gmail."""
    mailbox = _mailbox_owner(str(report.metadata.get("mailbox_id") or "")) if report.source == "email" else None
    if mailbox is None:
        return None
    token, scopes = gmail.google_grant(mailbox["owner_user_id"])
    if any(scope not in scopes for scope in NEEDS):
        return {"note": "not blocked in Gmail: reconnect Gmail and allow Scam Stop to manage spam"}
    message_id = str(report.metadata.get("gmail_id") or "")
    if message_id:
        gmail.gmail_send(token, "POST", f"/messages/{message_id}/modify", {"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]})
    created = gmail.gmail_send(token, "POST", "/settings/filters",
                               {"criteria": {"from": target}, "action": {"addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]}})
    return {"kind": "gmail", "mailbox_id": mailbox["id"], "message_id": message_id, "filter_id": created.get("id", ""),
            "note": "blocked in Gmail: the email was moved to Spam and a filter sends their future emails to the Bin"}


def unblock_in_gmail(block: dict) -> None:
    """Remove the filter and put the email back in the inbox."""
    if block.get("kind") != "gmail":
        return
    mailbox = _mailbox_owner(block.get("mailbox_id", ""))
    if mailbox is None:
        return
    token = gmail.google_token(mailbox["owner_user_id"])
    if block.get("filter_id"):
        gmail.gmail_send(token, "DELETE", f"/settings/filters/{block['filter_id']}")
    if block.get("message_id"):
        gmail.gmail_send(token, "POST", f"/messages/{block['message_id']}/modify", {"addLabelIds": ["INBOX"], "removeLabelIds": ["SPAM"]})


def register() -> None:
    """Plug the Gmail blocker into the agent's sender-marking tool. Called once by main.py."""
    if block_in_gmail not in tools.SENDER_BLOCKERS:
        tools.SENDER_BLOCKERS.append(block_in_gmail)
        tools.SENDER_UNBLOCKERS.append(unblock_in_gmail)
