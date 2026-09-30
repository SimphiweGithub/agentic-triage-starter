"""Domain boundary for incoming records and judge facing outputs."""
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from domain.enums import ActionOutcome, ActionType, IncidentState, Relationship, ServiceDomain, SeverityLevel


class RawInputReport(BaseModel):
    report_id: str = Field(min_length=1)
    timestamp: str = ""
    source: str = ""
    payload: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionProposal(BaseModel):
    type: ActionType
    service: ServiceDomain = ServiceDomain.UNSPECIFIED
    details: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class ActionRecord(BaseModel):
    report_id: str
    action: ActionProposal
    outcome: ActionOutcome
    detail: str = ""


class Assessment(BaseModel):
    severity: SeverityLevel
    confidence: float = Field(ge=0, le=1)
    requested_state: IncidentState
    proposed_action: ActionProposal | None = None
    rationale: str
    # Set when the evidence itself needs a human (conflict, uncertainty), with or without an action.
    review_reason: str | None = None
    # Seconds a human must wait before approving the review this assessment opens. 0 means no wait.
    review_delay_seconds: int = 0
    labels: dict[str, str] = Field(default_factory=dict)


class IncidentRecord(BaseModel):
    incident_id: str
    status: IncidentState
    severity: SeverityLevel
    confidence: float = Field(ge=0, le=1)
    report_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    updated_at: str = ""
    # Sticky: stays set after a review trigger until domain.logic.risk_persists says the risk is gone.
    review_hold: str | None = None
    actions: list[ActionRecord] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)


class DecisionRecord(BaseModel):
    report_id: str
    incident_id: str
    relationship: Relationship
    status: IncidentState
    severity: SeverityLevel
    confidence: float = Field(ge=0, le=1)
    proposed_action: ActionProposal | None = None
    action_outcome: ActionOutcome = ActionOutcome.NONE
    suppressed_action: ActionProposal | None = None
    requires_human_approval: bool
    review_id: str | None = None
    previous_status: IncidentState | None = None
    previous_severity: SeverityLevel | None = None
    previous_confidence: float | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    trace: list[str] = Field(default_factory=list)


class ReviewItem(BaseModel):
    review_id: str
    report_id: str
    incident_id: str
    reason: str
    proposed_action: ActionProposal | None = None
    status: str = "PENDING"
    audience: str = "CAREGIVER"   # who is asked: CAREGIVER, or PERSON when no guardian is enrolled
    not_before: str | None = None  # cooling-off: approval is refused until this time
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
