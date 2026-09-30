"""The HTTP API. Every route is under /api. Interactive documentation is served at /docs."""
from datetime import datetime, timezone
from pathlib import PurePath

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.ingest import kept, read_text_records, safe_parse
from core.runtime import TriageRuntime
from domain.enums import IncidentState
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


class Feedback(BaseModel):
    legitimate: bool


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


# ---- intake: how messages get in ----

@router.post("/intake/email", tags=["intake"], response_model=DecisionRecord | Withheld)
def intake_email(upload: EmailUpload):
    """A forwarded or saved email, as raw .eml text."""
    return _take_in(email_to_row(upload.content))


@router.post("/intake/share", tags=["intake"], response_model=DecisionRecord | Withheld)
def intake_share(message: SharedMessage):
    """A message shared by hand from the phone, for example an SMS."""
    return _take_in(share_to_row(message.text, message.sender, message.channel, _now()))


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
def reviews(status: str | None = None):
    """The review queue. Pass ?status=PENDING for what still needs the caregiver."""
    return [item for item in runtime.snapshot()["reviews"] if status is None or item.status == status]


@router.post("/reviews/{review_id}/decision", tags=["caregiver"], response_model=ReviewItem)
def decide(review_id: str, decision: ReviewDecision):
    """Approve or reject. An approved action runs now; a rejected one never runs."""
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
    return {"status": "ok"}


@router.get("/state", tags=["system"])
def state():
    """Everything in one call: reports, incidents, decisions, reviews, replay progress and the simulated world."""
    return {**runtime.snapshot(), "world": {"outbox": WORLD.outbox, "flagged": sorted(WORLD.flagged),
            "disputes": WORLD.disputes, "blocked": sorted(WORLD.blocked), "trusted": sorted(WORLD.trusted)}}


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
