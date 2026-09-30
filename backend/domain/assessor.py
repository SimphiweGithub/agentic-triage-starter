"""Optional LLM assessment. Output is a typed proposal; policy and the FSM still decide."""
import json
from pathlib import Path

from pydantic import BaseModel, Field

from core.client import call_agent_structured
from domain.enums import ActionType, IncidentState, ServiceDomain, SeverityLevel
from domain.schemas import ActionProposal, Assessment, IncidentRecord, RawInputReport


class AssessmentVerdict(BaseModel):
    severity: SeverityLevel
    confidence: float = Field(ge=0, le=1)
    requested_state: IncidentState
    action_type: ActionType | None = None
    service: ServiceDomain | None = None
    review_reason: str | None = None
    rationale: str


def llm_assess(report: RawInputReport, incident: IncidentRecord, history: list[RawInputReport]) -> Assessment:
    instructions = (Path(__file__).resolve().parents[1] / "prompts" / "assess.md").read_text(encoding="utf-8")
    prompt = instructions + "\n\nNew report:\n" + report.model_dump_json() + "\n\nIncident so far:\n"
    prompt += json.dumps({"incident": incident.model_dump(mode="json"),
                          "reports": [item.model_dump(mode="json") for item in history]}, ensure_ascii=False)
    verdict = call_agent_structured(prompt, AssessmentVerdict)
    action = None
    if verdict.action_type is not None:
        action = ActionProposal(type=verdict.action_type, service=verdict.service or ServiceDomain.UNSPECIFIED)
    return Assessment(severity=verdict.severity, confidence=verdict.confidence, requested_state=verdict.requested_state,
                      proposed_action=action, rationale=verdict.rationale, review_reason=verdict.review_reason or None)
