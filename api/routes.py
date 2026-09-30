from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.runtime import TriageRuntime
from domain.enums import IncidentState
from domain.schemas import RawInputReport

router = APIRouter()
runtime = TriageRuntime()


class ReviewDecision(BaseModel):
    approved: bool


class StateRequest(BaseModel):
    target: IncidentState


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/state")
def state():
    return runtime.snapshot()


@router.post("/reports", status_code=201)
def ingest(report: RawInputReport):
    try:
        return runtime.process(report)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/replay")
def replay(reports: list[RawInputReport]):
    with runtime.lock:
        runtime.reset()
        for report in reports:
            runtime.process(report)
        return runtime.snapshot()


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str):
    snapshot = runtime.snapshot()
    incident = next((item for item in snapshot["incidents"] if item.incident_id == incident_id), None)
    if incident is None:
        raise HTTPException(404, "Incident not found")
    ids = set(incident.report_ids)
    return {"incident": incident, "reports": [item for item in snapshot["reports"] if item.report_id in ids],
            "decisions": [item for item in snapshot["decisions"] if item.incident_id == incident_id],
            "reviews": [item for item in snapshot["reviews"] if item.incident_id == incident_id]}


@router.post("/reviews/{review_id}/decision")
def decide(review_id: str, decision: ReviewDecision):
    try:
        return runtime.decide_review(review_id, decision.approved)
    except KeyError as error:
        raise HTTPException(404, "Review not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/incidents/{incident_id}/state")
def move_state(incident_id: str, request: StateRequest):
    try:
        return runtime.move_state(incident_id, request.target)
    except KeyError as error:
        raise HTTPException(404, "Incident not found") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.post("/reset")
def reset():
    runtime.reset()
    return {"status": "reset"}
