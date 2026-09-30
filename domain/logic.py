"""Challenge swap point: input mapping, candidate text, and assessment rules."""
from typing import Any

from domain.enums import IncidentState, SeverityLevel
from domain.schemas import Assessment, IncidentRecord, RawInputReport


def parse_record(data: dict[str, Any]) -> RawInputReport:
    return RawInputReport.model_validate(data)


def correlation_text(report: RawInputReport) -> str:
    return f"{report.source} {report.payload}".strip()


def assess(report: RawInputReport, incident: IncidentRecord) -> Assessment:
    """Conservative placeholder; replace after the challenge is known."""
    target = IncidentState.TRIAGED if incident.status is IncidentState.NEW else IncidentState.INVESTIGATING
    return Assessment(
        severity=SeverityLevel.LOW,
        confidence=0.5,
        requested_state=target,
        proposed_action=None,
        rationale="No challenge rules configured; no action proposed.",
    )
