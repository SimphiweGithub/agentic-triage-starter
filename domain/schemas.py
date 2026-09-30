"""Domain boundary for incoming records and judge facing outputs."""
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from domain.enums import ActionType, IncidentState, Relationship, ServiceDomain, SeverityLevel


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


class Assessment(BaseModel):
    severity: SeverityLevel
    confidence: float = Field(ge=0, le=1)
    requested_state: IncidentState
    proposed_action: ActionProposal | None = None
    rationale: str


class IncidentRecord(BaseModel):
    incident_id: str
    status: IncidentState
    severity: SeverityLevel
    confidence: float = Field(ge=0, le=1)
    report_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    updated_at: str = ""


class DecisionRecord(BaseModel):
    report_id: str
    incident_id: str
    relationship: Relationship
    status: IncidentState
    severity: SeverityLevel
    confidence: float = Field(ge=0, le=1)
    proposed_action: ActionProposal | None = None
    requires_human_approval: bool
    review_id: str | None = None
    trace: list[str] = Field(default_factory=list)


class ReviewItem(BaseModel):
    review_id: str
    report_id: str
    incident_id: str
    reason: str
    proposed_action: ActionProposal | None = None
    status: str = "PENDING"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
