"""The HTTP API. Every route is under /api. Interactive documentation is served at /docs."""
from datetime import datetime, timezone
import os
from pathlib import PurePath

from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.ingest import kept, read_text_records, safe_parse
from core.runtime import TriageRuntime
from domain.briefs import guardian_brief
from domain.enums import IncidentState
from domain.extract import OTP_PATTERN, SECRET_PATTERN
from domain.intake import email_to_row, share_to_row
from domain.logic import withhold
from domain.schemas import DecisionRecord, IncidentRecord, RawInputReport, ReviewItem
from domain.tools import WORLD

router = APIRouter()
runtime = TriageRuntime()


class ReviewDecision(BaseModel):
    approved: bool


class StateRequest(BaseModel):
    target: IncidentState


class ReplayFile(BaseModel):
    filename: str
    content: str


class StepRequest(BaseModel):
    steps: int = Field(default=1, ge=1)


class EmailUpload(BaseModel):
    content: str


class SharedMessage(BaseModel):
    text: str = Field(min_length=1)
    sender: str = ""
    channel: str = "sms"
    # When the phone received it, in ISO format. A phone app syncing its inbox should always send this:
    # the same message sent twice then has the same id and is not processed twice.
    timestamp: str = ""


class Feedback(BaseModel):
    legitimate: bool


class GuardianSetting(BaseModel):
    enrolled: bool


class Withheld(BaseModel):
    status: str = "withheld"
    reason: str


class PersonMessage(BaseModel):
    incident_id: str
    message: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _take_in(row: dict) -> DecisionRecord | Withheld:
    """Shared path for live intake: discard what must not be stored, otherwise process it."""
    reason = withhold(row)
    if reason:
        return Withheld(reason=reason)
    report, error = safe_parse(row, len(runtime.decisions) + 1)
    return runtime.process_safely(report, error)


def take_in_email(raw: str) -> DecisionRecord | Withheld:
    """One raw email, from the API or from the live mailbox."""
    return _take_in(email_to_row(raw))


# ---- intake: how messages get in ----

@router.post("/intake/email", tags=["intake"], response_model=DecisionRecord | Withheld)
def intake_email(upload: EmailUpload):
    """A forwarded or saved email, as raw .eml text."""
    return take_in_email(upload.content)


@router.post("/intake/share", tags=["intake"], response_model=DecisionRecord | Withheld)
def intake_share(message: SharedMessage):
    """A message shared by hand from the phone, for example an SMS."""
    return _take_in(share_to_row(message.text, message.sender, message.channel, message.timestamp or _now()))


@router.post("/intake/share/batch", tags=["intake"], response_model=list[DecisionRecord | Withheld])
def intake_share_batch(messages: list[SharedMessage]):
    """Many messages at once, oldest first, for a phone app syncing its SMS inbox. Messages already seen are not reprocessed."""
    return [intake_share(message) for message in messages]


@router.get("/privacy/patterns", tags=["intake"])
def privacy_patterns():
    """The patterns for messages that must never leave the phone, so an app can apply the same filter before sending."""
    return {"withhold": [OTP_PATTERN.pattern, SECRET_PATTERN.pattern], "flags": "i"}


@router.post("/intake/whatsapp", tags=["intake"])
async def intake_whatsapp(request: Request):
    """Webhook for a WhatsApp gateway (Twilio format): a form with From and Body. The message is taken in like a shared SMS."""
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    text, sender = form.get("Body", [""])[0], form.get("From", [""])[0].removeprefix("whatsapp:")
    if text.strip():
        _take_in(share_to_row(text, sender, "whatsapp", _now()))
    return Response(content="<Response></Response>", media_type="application/xml")  # an empty reply: the agent never answers the sender


@router.post("/reports", tags=["intake"], status_code=201, response_model=DecisionRecord)
def ingest(report: RawInputReport):
    """A ready-made report. Most clients should use the two intake routes above instead."""
    try:
        return runtime.process(report)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


# ---- the protected person's view ----

@router.get("/outbox", tags=["person"], response_model=list[PersonMessage])
def outbox():
    """Warnings written for the protected person, oldest first."""
    return WORLD.outbox


@router.post("/incidents/{incident_id}/feedback", tags=["person"], response_model=DecisionRecord)
def feedback(incident_id: str, answer: Feedback):
    """The person's own answer about an incident. It is evidence, processed like any other report."""
    if incident_id not in runtime.incidents:
        raise HTTPException(404, "Incident not found")
    text = "The person says this is legitimate." if answer.legitimate else "The person says they did not agree to this."
    report = RawInputReport(report_id=f"F-{len(runtime.decisions) + 1:04d}", timestamp=_now(), source="person", payload=text,
                            metadata={"incident_id": incident_id, "feedback": "legitimate" if answer.legitimate else "not_mine"})
    return runtime.process_safely(report)


# ---- the caregiver's view ----

@router.get("/incidents", tags=["caregiver"], response_model=list[IncidentRecord])
def incidents():
    """Every incident with its current state, severity, labels and action history."""
    return runtime.snapshot()["incidents"]


@router.get("/incidents/{incident_id}", tags=["caregiver"])
def incident_detail(incident_id: str):
    """One incident with the messages, decisions and reviews that belong to it."""
    snapshot = runtime.snapshot()
    incident = next((item for item in snapshot["incidents"] if item.incident_id == incident_id), None)
    if incident is None:
        raise HTTPException(404, "Incident not found")
    ids = set(incident.report_ids)
    return {"incident": incident, "reports": [item for item in snapshot["reports"] if item.report_id in ids],
            "decisions": [item for item in snapshot["decisions"] if item.incident_id == incident_id],
            "reviews": [item for item in snapshot["reviews"] if item.incident_id == incident_id]}


@router.get("/decisions/{report_id}", tags=["caregiver"], response_model=DecisionRecord)
def decision(report_id: str):
    """The decision and reasoning trace for one message."""
    if report_id not in runtime.decisions:
        raise HTTPException(404, "Decision not found")
    return runtime.decisions[report_id]


@router.get("/reviews", tags=["caregiver"], response_model=list[ReviewItem])
def reviews(status: str | None = None, audience: str | None = None):
    """The review queue. Filter with ?status=PENDING and ?audience=CAREGIVER or PERSON."""
    return [item for item in runtime.snapshot()["reviews"]
            if (status is None or item.status == status) and (audience is None or item.audience == audience)]


@router.get("/guardian/briefs", tags=["caregiver"])
def guardian_briefs():
    """Each review waiting for the caregiver as a short plain message, with a link that opens WhatsApp ready to send it."""
    return [guardian_brief(item, runtime.decisions[item.report_id]) for item in runtime.snapshot()["reviews"]
            if item.status == "PENDING" and item.audience == "CAREGIVER"]


@router.post("/reviews/{review_id}/decision", tags=["caregiver"], response_model=ReviewItem)
def decide(review_id: str, decision: ReviewDecision):
    """Approve or reject. An approved action runs now; a rejected one never runs. 409 during a cooling-off period."""
    try:
        return runtime.decide_review(review_id, decision.approved)
    except KeyError as error:
        raise HTTPException(404, "Review not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/incidents/{incident_id}/state", tags=["caregiver"], response_model=IncidentRecord)
def move_state(incident_id: str, request: StateRequest):
    """Move an incident by hand. Refused if the state machine does not allow it or a review is pending."""
    try:
        return runtime.move_state(incident_id, request.target)
    except KeyError as error:
        raise HTTPException(404, "Incident not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


# ---- everything at once, and demo controls ----

@router.get("/health", tags=["system"])
def health():
    """Confirms the server is up and says which optional parts are switched on."""
    return {"status": "ok", "mailbox": bool(os.getenv("IMAP_HOST")), "jev": os.getenv("ENABLE_JEV") == "1",
            "gemini": os.getenv("ENABLE_GEMINI") == "1", "live_lookups": os.getenv("KINGUARD_LIVE_LOOKUPS") == "1",
            "gmail": bool(os.getenv("CLERK_SECRET_KEY")), "guardian": WORLD.guardian}


@router.get("/state", tags=["system"])
def state():
    """Everything in one call: reports, incidents, decisions, reviews, replay progress and the simulated world."""
    return {**runtime.snapshot(), "world": {"outbox": WORLD.outbox, "flagged": sorted(WORLD.flagged),
            "disputes": WORLD.disputes, "blocked": sorted(WORLD.blocked), "trusted": sorted(WORLD.trusted),
            "guardian": WORLD.guardian}}


@router.post("/settings/guardian", tags=["system"])
def set_guardian(setting: GuardianSetting):
    """Say whether a caregiver is enrolled. With none, reviews are addressed to the person themselves."""
    WORLD.guardian = setting.enrolled
    return {"guardian": WORLD.guardian}


@router.post("/reset", tags=["system"])
def reset():
    """Empty everything, including the simulated world."""
    runtime.reset()
    return {"status": "reset"}


@router.post("/replay", tags=["system"])
def replay(reports: list[RawInputReport]):
    """Reset, then process a list of reports in one go."""
    with runtime.lock:
        runtime.reset()
        for report in reports:
            runtime.process(report)
        return runtime.snapshot()


@router.post("/replay/load", tags=["system"])
def replay_load(file: ReplayFile):
    """Queue a CSV or JSONL file for step-through replay in its original order."""
    try:
        rows = list(kept(read_text_records(file.content.lstrip("﻿"), PurePath(file.filename).suffix)))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    runtime.load_queue([safe_parse(row, index) for index, row in enumerate(rows, start=1)])
    return runtime.snapshot()


@router.post("/replay/step", tags=["system"])
def replay_step(request: StepRequest):
    """Process the next messages in the queued file."""
    runtime.step(request.steps)
    return runtime.snapshot()
