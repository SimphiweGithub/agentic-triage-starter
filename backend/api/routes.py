"""The HTTP API. Every route is under /api. Interactive documentation is served at /docs."""
from datetime import datetime, timezone
import os
from pathlib import PurePath

from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from twilio.request_validator import RequestValidator

from api.auth import Caller, active_caregiver_person, active_member_person, dev_open, member
from api.pool import default_runtime, runtime_for
from api.store import get_store
from core.ingest import kept, read_text_records, safe_parse
from core.runtime import TriageRuntime
from domain.briefs import guardian_brief
from domain.enums import IncidentState
from domain.intake import email_to_row, share_to_row
from domain.logic import withhold
from domain.schemas import DecisionRecord, IncidentRecord, RawInputReport, ReviewItem

router = APIRouter(dependencies=[Depends(active_caregiver_person)])   # the caregiver's routes, about one person in the address
person_router = APIRouter(dependencies=[Depends(active_member_person)])  # the few the protected person may also use
open_router = APIRouter()                                               # health: no session to check
gateway_router = APIRouter()                                            # the WhatsApp gateway, which cannot sign in; it names one person in its address
runtime = default_runtime()  # the shared runtime of the plain console and offline use; each person has their own (api/pool.py)


def caregiver_runtime(person_id: str | None = Depends(active_caregiver_person)) -> TriageRuntime:
    """The runtime of the person the caregiver's request is about."""
    return runtime_for(person_id) if person_id else default_runtime()


def member_runtime(person_id: str | None = Depends(active_member_person)) -> TriageRuntime:
    """The same for the routes the protected person may also use."""
    return runtime_for(person_id) if person_id else default_runtime()


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


def _take_in(row: dict, rt: TriageRuntime) -> DecisionRecord | Withheld:
    """Shared path for live intake: discard what must not be stored, otherwise process it for this person."""
    reason = withhold(row)
    if reason:
        return Withheld(reason=reason)
    report, error = safe_parse(row, rt.next_report_number())
    return rt.process_safely(report, error)


def take_in_email(raw: str, rt: TriageRuntime | None = None) -> DecisionRecord | Withheld:
    """One raw email, from the API or from a mailbox, for one person's runtime (the shared one if none is given)."""
    return _take_in(email_to_row(raw), rt or default_runtime())


# ---- intake: how messages get in ----

@router.post("/intake/email", tags=["intake"], response_model=DecisionRecord | Withheld)
def intake_email(upload: EmailUpload, rt: TriageRuntime = Depends(caregiver_runtime)):
    """A forwarded or saved email, as raw .eml text."""
    return take_in_email(upload.content, rt)


@router.post("/intake/share", tags=["intake"], response_model=DecisionRecord | Withheld)
def intake_share(message: SharedMessage, rt: TriageRuntime = Depends(caregiver_runtime)):
    """A message shared by hand from the phone, for example an SMS."""
    return _take_in(share_to_row(message.text, message.sender, message.channel, _now()), rt)


@gateway_router.post("/intake/whatsapp", tags=["intake"])
async def intake_whatsapp(request: Request, person_id: str | None = None):
    """Webhook for a WhatsApp gateway (Twilio format): a form with From and Body. The gateway is pointed at one person's address. The message is taken in like a shared SMS."""
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    if not dev_open():
        token = os.getenv("TWILIO_AUTH_TOKEN")
        if not token:
            raise HTTPException(503, "WhatsApp webhook is not configured")
        origin = os.getenv("TWILIO_PUBLIC_ORIGIN", "").rstrip("/")
        url = f"{origin}{request.url.path}" if origin else str(request.url).split("?", 1)[0]
        if request.url.query:
            url += f"?{request.url.query}"
        fields = {key: values[0] for key, values in form.items()}
        if not RequestValidator(token).validate(url, fields, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403, "Invalid WhatsApp gateway signature")
    if person_id is not None and get_store().person(person_id) is None:
        raise HTTPException(404, "Person not found")
    rt = runtime_for(person_id) if person_id else default_runtime()
    text, sender = form.get("Body", [""])[0], form.get("From", [""])[0].removeprefix("whatsapp:")
    if text.strip():
        _take_in(share_to_row(text, sender, "whatsapp", _now()), rt)
    return Response(content="<Response></Response>", media_type="application/xml")  # an empty reply: the agent never answers the sender


@router.post("/reports", tags=["intake"], status_code=201, response_model=DecisionRecord)
def ingest(report: RawInputReport, rt: TriageRuntime = Depends(caregiver_runtime)):
    """A ready-made report. Most clients should use the two intake routes above instead."""
    try:
        return rt.process(report)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


# ---- the protected person's view ----

@person_router.get("/outbox", tags=["person"], response_model=list[PersonMessage])
def outbox(rt: TriageRuntime = Depends(member_runtime)):
    """Warnings written for the protected person, oldest first."""
    answered = {report.metadata.get("incident_id") for report in rt.reports.values() if report.metadata.get("feedback")}
    return [item for item in rt.world.outbox if item["incident_id"] not in answered]


@person_router.post("/incidents/{incident_id}/feedback", tags=["person"], response_model=DecisionRecord)
def feedback(incident_id: str, answer: Feedback, rt: TriageRuntime = Depends(member_runtime), me: Caller = Depends(member)):
    """The person's own answer about an incident. It is evidence, processed like any other report."""
    if not dev_open() and me.role != "person":
        raise HTTPException(403, "Only the person can answer about their own incident")
    if incident_id not in rt.incidents:
        raise HTTPException(404, "Incident not found")
    text = "The person says this is legitimate." if answer.legitimate else "The person says they did not agree to this."
    report = RawInputReport(report_id=f"F-{rt.next_report_number():04d}", timestamp=_now(), source="person", payload=text,
                            metadata={"incident_id": incident_id, "feedback": "legitimate" if answer.legitimate else "not_mine"})
    return rt.process_safely(report)


# ---- the caregiver's view ----

@router.get("/incidents", tags=["caregiver"], response_model=list[IncidentRecord])
def incidents(rt: TriageRuntime = Depends(caregiver_runtime)):
    """Every incident with its current state, severity, labels and action history."""
    return rt.snapshot()["incidents"]


@router.get("/incidents/{incident_id}", tags=["caregiver"])
def incident_detail(incident_id: str, rt: TriageRuntime = Depends(caregiver_runtime)):
    """One incident with the messages, decisions and reviews that belong to it."""
    snapshot = rt.snapshot()
    incident = next((item for item in snapshot["incidents"] if item.incident_id == incident_id), None)
    if incident is None:
        raise HTTPException(404, "Incident not found")
    ids = set(incident.report_ids)
    return {"incident": incident, "reports": [item for item in snapshot["reports"] if item.report_id in ids],
            "decisions": [item for item in snapshot["decisions"] if item.incident_id == incident_id],
            "reviews": [item for item in snapshot["reviews"] if item.incident_id == incident_id]}


@router.get("/decisions/{report_id}", tags=["caregiver"], response_model=DecisionRecord)
def decision(report_id: str, rt: TriageRuntime = Depends(caregiver_runtime)):
    """The decision and reasoning trace for one message."""
    if report_id not in rt.decisions:
        raise HTTPException(404, "Decision not found")
    return rt.decisions[report_id]


@router.get("/reviews", tags=["caregiver"], response_model=list[ReviewItem])
def reviews(status: str | None = None, audience: str | None = None, rt: TriageRuntime = Depends(caregiver_runtime)):
    """The review queue. Filter with ?status=PENDING and ?audience=CAREGIVER or PERSON."""
    return [item for item in rt.snapshot()["reviews"]
            if (status is None or item.status == status) and (audience is None or item.audience == audience)]


@router.get("/guardian/briefs", tags=["caregiver"])
def guardian_briefs(rt: TriageRuntime = Depends(caregiver_runtime)):
    """Each review waiting for the caregiver as a short plain message, with a link that opens WhatsApp ready to send it."""
    return [guardian_brief(item, rt.decisions[item.report_id]) for item in rt.snapshot()["reviews"]
            if item.status == "PENDING" and item.audience == "CAREGIVER"]


@person_router.get("/person/reviews", tags=["person"], response_model=list[ReviewItem])
def person_reviews(status: str | None = None, rt: TriageRuntime = Depends(member_runtime)):
    """Only questions addressed to the protected person, without exposing caregiver reviews."""
    return [item for item in rt.snapshot()["reviews"] if item.audience == "PERSON" and (status is None or item.status == status)]


@person_router.post("/reviews/{review_id}/decision", tags=["person"], response_model=ReviewItem)
def decide(review_id: str, decision: ReviewDecision, rt: TriageRuntime = Depends(member_runtime), me: Caller = Depends(member)):
    """Approve or reject. An approved action runs now; a rejected one never runs. 409 during a cooling-off period."""
    try:
        review = rt.reviews[review_id]
        if not dev_open() and review.audience != ("PERSON" if me.role == "person" else "CAREGIVER"):
            raise HTTPException(403, "This decision is addressed to someone else")
        return rt.decide_review(review_id, decision.approved)
    except KeyError as error:
        raise HTTPException(404, "Review not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/incidents/{incident_id}/state", tags=["caregiver"], response_model=IncidentRecord)
def move_state(incident_id: str, request: StateRequest, rt: TriageRuntime = Depends(caregiver_runtime)):
    """Move an incident by hand. Refused if the state machine does not allow it or a review is pending."""
    try:
        return rt.move_state(incident_id, request.target)
    except KeyError as error:
        raise HTTPException(404, "Incident not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


# ---- everything at once, and demo controls ----

@open_router.get("/health", tags=["system"])
def health():
    """Confirms the server is up and says which optional parts are switched on."""
    return {"status": "ok", "mailbox": bool(os.getenv("IMAP_HOST")), "jev": os.getenv("ENABLE_JEV") == "1",
            "gemini": os.getenv("ENABLE_GEMINI") == "1", "live_lookups": os.getenv("KINGUARD_LIVE_LOOKUPS") == "1",
            "gmail": bool(os.getenv("CLERK_SECRET_KEY"))}


@router.get("/state", tags=["system"])
def state(rt: TriageRuntime = Depends(caregiver_runtime)):
    """Everything in one call: reports, incidents, decisions, reviews, replay progress and the simulated world."""
    return {**rt.snapshot(), "world": {"outbox": rt.world.outbox, "flagged": sorted(rt.world.flagged),
            "disputes": rt.world.disputes, "blocked": sorted(rt.world.blocked), "trusted": sorted(rt.world.trusted),
            "guardian": rt.world.guardian}}


@router.post("/settings/guardian", tags=["system"])
def set_guardian(setting: GuardianSetting, rt: TriageRuntime = Depends(caregiver_runtime)):
    """Say whether a caregiver is enrolled. With none, reviews are addressed to the person themselves."""
    rt.world.guardian = setting.enrolled
    return {"guardian": rt.world.guardian}


@router.post("/reset", tags=["system"])
def reset(rt: TriageRuntime = Depends(caregiver_runtime)):
    """Empty everything, including the simulated world."""
    rt.reset()
    return {"status": "reset"}


@router.post("/replay", tags=["system"])
def replay(reports: list[RawInputReport], rt: TriageRuntime = Depends(caregiver_runtime)):
    """Reset, then process a list of reports in one go."""
    with rt.lock:
        rt.reset()
        for report in reports:
            rt.process(report)
        return rt.snapshot()


@router.post("/replay/load", tags=["system"])
def replay_load(file: ReplayFile, rt: TriageRuntime = Depends(caregiver_runtime)):
    """Queue a CSV or JSONL file for step-through replay in its original order."""
    try:
        rows = list(kept(read_text_records(file.content.lstrip("﻿"), PurePath(file.filename).suffix)))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    rt.load_queue([safe_parse(row, index) for index, row in enumerate(rows, start=1)])
    return rt.snapshot()


@router.post("/replay/step", tags=["system"])
def replay_step(request: StepRequest, rt: TriageRuntime = Depends(caregiver_runtime)):
    """Process the next messages in the queued file."""
    rt.step(request.steps)
    return rt.snapshot()
