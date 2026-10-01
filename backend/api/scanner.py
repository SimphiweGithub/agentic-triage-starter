"""Reads each connected mailbox in the background and keeps only what the caregiver needs.

Safe mail leaves no trace except an id and a verdict. Flagged mail keeps its text until
its alert is resolved, then the text is blanked too. The caregiver never browses the mailbox.
"""
import hashlib
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime

from fastapi import HTTPException

from api.gmail import google_token, message_ids, raw_email
from api.pool import all_runtimes, runtime_for
from api.routes import Withheld, take_in_email
from api.store import Store, get_store
from domain.enums import IncidentState
from core.runtime import TriageRuntime
from domain.schemas import DecisionRecord

BACKFILL_DAYS = 14
OVERLAP_SECONDS = 120  # look slightly before the last check so nothing slips between two scans
RESOLVED = (IncidentState.RESOLVED, IncidentState.CLOSED)


def handle_mail(mailbox: dict, raw: str) -> str:
    """Take one email in for the mailbox's person and apply the retention rules. Returns the verdict: safe, flagged or withheld."""
    rt = runtime_for(mailbox["person_id"])
    origin = {"mailbox_id": mailbox["id"], "gmail_id": mailbox["message_id"]} if mailbox.get("message_id") else None
    result = take_in_email(raw, rt, origin)
    if isinstance(result, Withheld):
        return "withheld"  # a one-time code: nothing was stored
    if result.labels.get("threat") == "BENIGN":
        forget(result, rt)
        rt.save()  # otherwise the saved file would still hold the safe email
        return "safe"
    with rt.lock:
        rt.reports[result.report_id].metadata["origin"] = f"mailbox:{mailbox['id']}"  # so it can be blanked when resolved
    rt.save()
    return "flagged"


def forget(decision: DecisionRecord, rt: TriageRuntime) -> None:
    """Remove safe mail from memory; keep an empty audit stub only when another record refers to it."""
    with rt.lock:
        incident = rt.incidents.get(decision.incident_id)
        if incident is None:
            return
        if incident.report_ids == [decision.report_id]:
            rt.incidents.pop(decision.incident_id)
        elif not any(item.report_id == decision.report_id for item in incident.actions) and not any(
                item.report_id == decision.report_id for item in rt.reviews.values()):
            incident.report_ids.remove(decision.report_id)
        else:
            report = rt.reports[decision.report_id]
            report.payload, report.metadata = "", {"verdict": "safe"}
            return
        rt.decisions.pop(decision.report_id, None)
        rt.reports.pop(decision.report_id, None)


def blank_resolved() -> int:
    """Blank the text of mailbox mail whose alert is resolved, for every person. Returns how many messages were blanked."""
    blanked = 0
    for rt in all_runtimes():
        before = blanked
        with rt.lock:
            for incident in rt.incidents.values():
                if incident.status not in RESOLVED:
                    continue
                from_mailbox = False
                for report_id in incident.report_ids:
                    report = rt.reports.get(report_id)
                    if report and str(report.metadata.get("origin", "")).startswith("mailbox:"):
                        from_mailbox = True
                        if report.payload:
                            report.payload, report.metadata = "", {"origin": report.metadata["origin"], "blanked": True}
                            blanked += 1
                if from_mailbox:
                    incident.summary = ""  # the summary is the first 240 characters of a message
            if blanked > before:
                rt.save()  # blank the saved copy too
    return blanked


def scan_gmail(store: Store, mailbox: dict, handle: Callable[[dict, str], str] = handle_mail) -> int:
    """One pass over one Gmail mailbox. Returns how many new emails were read."""
    if mailbox["last_checked"]:
        since = int(datetime.fromisoformat(mailbox["last_checked"]).timestamp()) - OVERLAP_SECONDS
        query = f"in:inbox after:{since}"
    else:
        query = f"in:inbox newer_than:{BACKFILL_DAYS}d"  # first connection: look back a fortnight
    read = 0
    try:
        token = google_token(mailbox["owner_user_id"])
        for message_id in message_ids(token, query):
            current = store.mailbox(mailbox["id"])
            if current is None or current["status"] == "disconnected" or current["owner_user_id"] != mailbox["owner_user_id"]:
                return read
            if store.seen(mailbox["id"], message_id):
                continue
            raw = raw_email(token, message_id)
            current = store.mailbox(mailbox["id"])
            if current is None or current["status"] == "disconnected" or current["owner_user_id"] != mailbox["owner_user_id"]:
                return read
            store.record_scanned(mailbox["id"], message_id, handle({**mailbox, "message_id": message_id}, raw))
            read += 1
        store.mark_checked(mailbox["id"])
    except HTTPException as error:
        store.mark_failure(mailbox["id"], str(error.detail), permanent=error.status_code in (401, 403))
    except Exception as error:  # a network blip must never stop the scanner
        store.mark_failure(mailbox["id"], f"{type(error).__name__}", permanent=False)
    return read


def scan_once(store: Store, handle: Callable[[dict, str], str] = handle_mail) -> int:
    """One pass over every Gmail mailbox that is still wanted, then blank what is resolved."""
    read = sum(scan_gmail(store, mailbox, handle) for mailbox in store.mailboxes()
               if mailbox["kind"] == "gmail" and mailbox["status"] != "disconnected")
    blank_resolved()
    return read


def forwarded_handler(store: Store) -> Callable[[str], None]:
    """For the server's own IMAP mailbox: the same retention rules, and a verdict kept per email, for the person it belongs to."""
    def handle(raw: str) -> None:
        for mailbox in store.mailboxes():
            if mailbox["kind"] == "forwarded":
                store.record_scanned(mailbox["id"], "imap:" + hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16], handle_mail(mailbox, raw))
                return
        take_in_email(raw)  # nobody is being looked after yet: behave as before
    return handle


def note_forwarded(store: Store, error: str | None) -> None:
    """Record whether the last IMAP check worked, on the forwarded mailbox."""
    for mailbox in store.mailboxes():
        if mailbox["kind"] == "forwarded":
            if error is None:
                store.mark_checked(mailbox["id"])
            else:
                store.mark_failure(mailbox["id"], error, permanent=False)


def start_scanning(store: Store | None = None) -> threading.Thread | None:
    """Start the background scan. Does nothing unless Clerk is configured, since the token comes from Clerk."""
    if not os.getenv("CLERK_SECRET_KEY"):
        return None
    store = store or get_store()
    seconds = float(os.getenv("SCAN_SECONDS", "60"))

    def loop() -> None:
        while True:
            try:
                scan_once(store)
            except Exception as error:  # the scanner must never stop the server
                print(f"mailbox scan failed: {type(error).__name__}: {error}")
            time.sleep(seconds)

    thread = threading.Thread(target=loop, daemon=True, name="scanner")
    thread.start()
    return thread
