"""Domain-neutral, in-memory orchestration and audit trail."""
from datetime import datetime, timezone
from itertools import count
import os
from threading import RLock

from core.correlator import Correlator
from core.fsm import transition_state
from core.guardrails import enforce_action_safety
from domain.enums import IncidentState, Relationship, SeverityLevel
from domain.logic import assess
from domain.schemas import DecisionRecord, IncidentRecord, RawInputReport, ReviewItem


class TriageRuntime:
    def __init__(self, correlator: Correlator | None = None):
        self.lock = RLock()
        if correlator is None and os.getenv("ENABLE_LLM_RELATION") == "1":
            if not os.getenv("GEMINI_API_KEY"):
                raise RuntimeError("ENABLE_LLM_RELATION requires GEMINI_API_KEY")
            from domain.relation import resolve_relation
            correlator = Correlator(relation_resolver=resolve_relation)
        self.correlator = correlator or Correlator()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.reports: dict[str, RawInputReport] = {}
            self.incidents: dict[str, IncidentRecord] = {}
            self.decisions: dict[str, DecisionRecord] = {}
            self.reviews: dict[str, ReviewItem] = {}
            self._incident_ids = count(1)
            self._review_ids = count(1)

    def process(self, report: RawInputReport) -> DecisionRecord:
        with self.lock:
            if report.report_id in self.decisions:
                if self.reports[report.report_id] != report:
                    raise ValueError("report_id already exists with different content")
                return self.decisions[report.report_id]
            match = self.correlator.match(report, self.incidents, self.reports)
            if match.incident_id is None:
                incident = IncidentRecord(incident_id=f"I{next(self._incident_ids):04d}", status=IncidentState.NEW,
                                          severity=SeverityLevel.LOW, confidence=0, summary=report.payload[:240])
                self.incidents[incident.incident_id] = incident
            else:
                incident = self.incidents[match.incident_id]
            assessment = assess(report, incident)
            if match.relationship is Relationship.DUPLICATE:
                assessment.proposed_action = None
            next_state = transition_state(incident.status, assessment.requested_state)
            illegal = next_state is IncidentState.PENDING_REVIEW and assessment.requested_state is not IncidentState.PENDING_REVIEW
            state_review = next_state is IncidentState.PENDING_REVIEW
            safety = enforce_action_safety(assessment.proposed_action, assessment.confidence)
            open_review = any(item.incident_id == incident.incident_id and item.status == "PENDING" for item in self.reviews.values())
            requires_review = state_review or safety.requires_review or open_review
            if requires_review:
                next_state = IncidentState.PENDING_REVIEW
            incident.status = next_state
            incident.severity = assessment.severity
            incident.confidence = assessment.confidence
            incident.report_ids.append(report.report_id)
            incident.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            trace = [f"Correlation: {match.relationship.value} ({match.score:.3f})", assessment.rationale,
                     f"FSM: {assessment.requested_state.value} → {next_state.value}", f"Policy: {safety.reason}"]
            review_id = None
            if state_review or safety.requires_review:
                review_id = f"REV-{next(self._review_ids):04d}"
                reason = "Illegal lifecycle transition" if illegal else "State requires human review" if state_review else safety.reason
                self.reviews[review_id] = ReviewItem(review_id=review_id, report_id=report.report_id,
                    incident_id=incident.incident_id, reason=reason, proposed_action=assessment.proposed_action)
            decision = DecisionRecord(report_id=report.report_id, incident_id=incident.incident_id,
                relationship=match.relationship, status=next_state, severity=incident.severity,
                confidence=incident.confidence, proposed_action=assessment.proposed_action,
                requires_human_approval=requires_review, review_id=review_id, trace=trace)
            self.reports[report.report_id] = report
            self.decisions[report.report_id] = decision
            return decision

    def decide_review(self, review_id: str, approved: bool) -> ReviewItem:
        with self.lock:
            item = self.reviews[review_id]
            if item.status != "PENDING":
                raise ValueError("Review already decided")
            # Approval records a human decision. A domain action executor is intentionally absent.
            item.status = "APPROVED_FOR_MANUAL_HANDLING" if approved else "REJECTED"
            return item

    def move_state(self, incident_id: str, target: IncidentState) -> IncidentRecord:
        with self.lock:
            incident = self.incidents[incident_id]
            if any(item.incident_id == incident_id and item.status == "PENDING" for item in self.reviews.values()):
                raise ValueError("Resolve pending reviews before moving state")
            next_state = transition_state(incident.status, target)
            if next_state is IncidentState.PENDING_REVIEW and target is not IncidentState.PENDING_REVIEW:
                raise ValueError("Requested transition is illegal")
            incident.status = next_state
            return incident

    def snapshot(self) -> dict:
        with self.lock:
            return {"reports": list(self.reports.values()), "incidents": list(self.incidents.values()),
                    "decisions": list(self.decisions.values()), "reviews": list(self.reviews.values())}
