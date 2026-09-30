"""Optional second-tier semantic relation resolver for candidate incidents."""
import json
from pathlib import Path

from pydantic import BaseModel, Field

from core.client import call_agent_structured
from domain.enums import Relationship
from domain.schemas import IncidentRecord, RawInputReport


class RelationVerdict(BaseModel):
    label: Relationship
    confidence: float = Field(ge=0, le=1)
    evidence: str


def resolve_relation(report: RawInputReport, incident: IncidentRecord, history: list[RawInputReport]) -> Relationship:
    instructions = (Path(__file__).resolve().parents[1] / "prompts" / "relation.md").read_text(encoding="utf-8")
    prompt = instructions + "\n\nNew report:\n" + report.model_dump_json() + "\n\nCandidate incident:\n"
    prompt += json.dumps({"incident_id": incident.incident_id, "summary": incident.summary,
                          "reports": [item.model_dump(mode="json") for item in history]}, ensure_ascii=False)
    verdict = call_agent_structured(prompt, RelationVerdict)
    return verdict.label if verdict.confidence >= 0.75 else Relationship.NEW
