"""Domain-neutral orchestration and audit trail, saved to disk after every change (see core/store.py)."""
from datetime import datetime, timedelta, timezone
from itertools import count
import os
from threading import RLock

from core import store
from core.correlator import Correlator
from core.executor import execute_approved, execute_with_correction
from core.fsm import transition_state
from domain.enums import ActionOutcome, IncidentState, Relationship, SeverityLevel
from domain.logic import assess, learn_from_review, review_audience, risk_persists
from domain.policy import ACTION_IDENTITY, REPEATABLE_ACTIONS, STATE_AFTER_APPROVED, SUPERSEDING_ACTIONS
from domain.schemas import ActionRecord, Assessment, DecisionRecord, IncidentRecord, RawInputReport, ReviewItem
from domain.tools import reset_world

ENGAGED = (ActionOutcome.PROPOSED, ActionOutcome.EXECUTED, ActionOutcome.HELD_FOR_REVIEW)


class TriageRuntime:
    def __init__(self, correlator: Correlator | None = None):
        self.lock = RLock()
        if not os.getenv("GEMINI_API_KEY") and (os.getenv("ENABLE_LLM_RELATION") == "1" or os.getenv("ENABLE_LLM_ASSESS") == "1"):
            raise RuntimeError("ENABLE_LLM_RELATION and ENABLE_LLM_ASSESS require GEMINI_API_KEY")
        if correlator is None and os.getenv("ENABLE_LLM_RELATION") == "1":
            from domain.relation import resolve_relation
            correlator = Correlator(relation_resolver=resolve_relation)
        self.correlator = correlator or Correlator()
        self.llm_assess = os.getenv("ENABLE_LLM_ASSESS") == "1"
        self.now = lambda: datetime.now(timezone.utc)  # replaceable, so tests can move time forward
        self._clear()
        if store.load(self):  # carry on from the last saved state; new ids continue after the highest saved one
            self._incident_ids = count(1 + max((int(key[1:]) for key in self.incidents if key[1:].isdigit()), default=0))
            self._review_ids = count(1 + max((int(key[4:]) for key in self.reviews if key[4:].isdigit()), default=0))

    def reset(self) -> None:
        with self.lock:
            self._clear()
            store.save(self)

    def save(self) -> None:
        with self.lock:
            store.save(self)

    def _clear(self) -> None:
        with self.lock:
            self.reports: dict[str, RawInputReport] = {}
            self.incidents: dict[str, IncidentRecord] = {}
            self.decisions: dict[str, DecisionRecord] = {}
            self.reviews: dict[str, ReviewItem] = {}
            self.queue: list[tuple[RawInputReport, str | None]] = []
            self.position = 0
            self._incident_ids = count(1)
            self._review_ids = count(1)
            reset_world()

    def _new_incident(self, report: RawInputReport) -> IncidentRecord:
        incident = IncidentRecord(incident_id=f"I{next(self._incident_ids):04d}", status=IncidentState.NEW,
                                  severity=SeverityLevel.LOW, confidence=0, summary=report.payload[:240])
        self.incidents[incident.incident_id] = incident
        return incident

    def _assess(self, report: RawInputReport, incident: IncidentRecord) -> Assessment:
        if self.llm_assess:
            try:
                from domain.assessor import llm_assess
                return llm_assess(report, incident, [self.reports[report_id] for report_id in incident.report_ids])
            except Exception as error:  # a model failure must not stop the run
                fallback = assess(report, incident)
                fallback.rationale += f" (LLM assessment unavailable: {type(error).__name__}; rules used)"
                return fallback
        return assess(report, incident)

    def _pending(self, incident_id: str) -> list[ReviewItem]:
        return [item for item in self.reviews.values() if item.incident_id == incident_id and item.status == "PENDING"]

    def _open_review(self, report: RawInputReport, incident: IncidentRecord, reason: str, action=None, delay_seconds: int = 0) -> str:
        """One pending review per incident and reason; later reports link to it rather than adding noise."""
        existing = next((item for item in self._pending(incident.incident_id) if item.reason == reason), None)
        if existing:
            return existing.review_id
        review_id = f"REV-{next(self._review_ids):04d}"
        not_before = (self.now() + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds") if delay_seconds else None
        self.reviews[review_id] = ReviewItem(review_id=review_id, report_id=report.report_id, incident_id=incident.incident_id,
                                             reason=reason, proposed_action=action, audience=review_audience(), not_before=not_before)
        return review_id

    def process(self, report: RawInputReport) -> DecisionRecord:
        with self.lock:
            if report.report_id in self.decisions:
                if self.reports[report.report_id] != report:
                    raise ValueError("report_id already exists with different content")
                return self.decisions[report.report_id]
            match = self.correlator.match(report, self.incidents, self.reports)
            incident = self._new_incident(report) if match.incident_id is None else self.incidents[match.incident_id]
            previous = (incident.status, incident.severity, incident.confidence) if match.incident_id else (None, None, None)
            assessment = self._assess(report, incident)
            trace = [f"Correlation: {match.relationship.value} ({match.score:.3f}) — {match.reason}", assessment.rationale]

            # Duplicate and repeat suppression: evidence is still recorded, the action is not taken again.
            action, suppressed, outcome = assessment.proposed_action, None, ActionOutcome.NONE
            if action is not None:
                if match.relationship is Relationship.DUPLICATE:
                    action, suppressed, outcome = None, action, ActionOutcome.SUPPRESSED_DUPLICATE
                elif action.type not in REPEATABLE_ACTIONS and any(
                        record.outcome in ENGAGED and record.action.type == action.type and record.action.service == action.service
                        and record.action.details.get(ACTION_IDENTITY.get(action.type)) == action.details.get(ACTION_IDENTITY.get(action.type))
                        for record in incident.actions):
                    action, suppressed, outcome = None, action, ActionOutcome.SUPPRESSED_REPEAT

            next_state = transition_state(incident.status, assessment.requested_state)
            illegal = next_state is IncidentState.PENDING_REVIEW and assessment.requested_state is not IncidentState.PENDING_REVIEW
            trace.append(f"FSM: {assessment.requested_state.value} → {next_state.value}")

            # Act, check, correct. Each attempt is gated by the guardrails inside the executor.
            attempts = execute_with_correction(action, assessment.confidence, incident, report) if action is not None else []
            action_trigger = None
            if attempts:
                action, outcome = attempts[-1].action, attempts[-1].outcome
                incident.actions.extend(attempts)
                trace += [f"Action: {item.action.type.value} → {item.outcome.value} ({item.detail})" for item in attempts]
                if outcome is ActionOutcome.HELD_FOR_REVIEW:
                    action_trigger = attempts[-1].detail
                elif outcome is ActionOutcome.FAILED:
                    action_trigger = f"Action failed and no correction worked: {attempts[-1].detail}"
                elif outcome is ActionOutcome.EXECUTED and action.type in SUPERSEDING_ACTIONS:
                    for item in self._pending(incident.incident_id):
                        item.status = "SUPERSEDED"
                        trace.append(f"Review {item.review_id} superseded by {action.type.value}")
            elif suppressed is not None:
                incident.actions.append(ActionRecord(report_id=report.report_id, action=suppressed, outcome=outcome))
                trace.append(f"Action: {suppressed.type.value} → {outcome.value}")
            else:
                trace.append("Policy: No action proposed")
            trigger = ("Illegal lifecycle transition" if illegal
                       else "State requires human review" if next_state is IncidentState.PENDING_REVIEW
                       else action_trigger or assessment.review_reason)

            # Sticky review: a trigger sets the hold; it clears only when no review is pending and the risk is gone.
            review_id = None
            if trigger:
                review_id = self._open_review(report, incident, trigger, action, assessment.review_delay_seconds)
                incident.review_hold = trigger
                trace.append(f"Review: {trigger} ({review_id})")
            pending = self._pending(incident.incident_id)
            if not trigger and incident.review_hold:
                if pending or risk_persists(incident, assessment):
                    trace.append(f"Review hold kept: {incident.review_hold}")
                else:
                    trace.append(f"Review hold cleared: {incident.review_hold}")
                    incident.review_hold = None
            requires_review = bool(trigger or pending or incident.review_hold)
            if trigger or pending:
                next_state = IncidentState.PENDING_REVIEW

            incident.status = next_state
            incident.severity = assessment.severity
            incident.confidence = assessment.confidence
            incident.labels.update(assessment.labels)
            incident.report_ids.append(report.report_id)
            incident.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            decision = DecisionRecord(report_id=report.report_id, incident_id=incident.incident_id,
                relationship=match.relationship, status=next_state, severity=incident.severity,
                confidence=incident.confidence, proposed_action=action, action_outcome=outcome, suppressed_action=suppressed,
                requires_human_approval=requires_review, review_id=review_id, previous_status=previous[0],
                previous_severity=previous[1], previous_confidence=previous[2], labels=dict(incident.labels), trace=trace)
            self.reports[report.report_id] = report
            self.decisions[report.report_id] = decision
            store.save(self)
            return decision

    def record_failure(self, report: RawInputReport, error: str) -> DecisionRecord:
        """A report the engine could not handle still gets a valid decision, routed to a human."""
        with self.lock:
            if report.report_id in self.decisions:
                report = report.model_copy(update={"report_id": f"{report.report_id}~{len(self.decisions) + 1}"})
            incident = self._new_incident(report)
            incident.status = transition_state(incident.status, IncidentState.PENDING_REVIEW)
            incident.review_hold = "Report could not be processed"
            incident.report_ids.append(report.report_id)
            incident.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            review_id = self._open_review(report, incident, incident.review_hold)
            decision = DecisionRecord(report_id=report.report_id, incident_id=incident.incident_id,
                relationship=Relationship.NEW, status=incident.status, severity=incident.severity,
                confidence=incident.confidence, requires_human_approval=True, review_id=review_id,
                trace=[f"Processing failed: {error}", "No assessment or action; sent to human review."])
            self.reports[report.report_id] = report
            self.decisions[report.report_id] = decision
            store.save(self)
            return decision

    def process_safely(self, report: RawInputReport, parse_error: str | None = None) -> DecisionRecord:
        """Batch entry point: one decision per input row, whatever happens."""
        if parse_error:
            return self.record_failure(report, parse_error)
        try:
            return self.process(report)
        except Exception as error:
            return self.record_failure(report, f"{type(error).__name__}: {error}")

    def load_queue(self, items: list[tuple[RawInputReport, str | None]]) -> None:
        with self.lock:
            self.reset()
            self.queue = list(items)

    def step(self, steps: int = 1) -> list[DecisionRecord]:
        with self.lock:
            batch = self.queue[self.position:self.position + max(steps, 0)]
            decisions = [self.process_safely(report, error) for report, error in batch]
            self.position += len(batch)
            return decisions

    def decide_review(self, review_id: str, approved: bool) -> ReviewItem:
        """Record the human decision. An approved action now runs; a rejected one never does."""
        with self.lock:
            item = self.reviews[review_id]
            if item.status != "PENDING":
                raise ValueError("Review already decided")
            if not approved:
                item.status = "REJECTED"
                learn_from_review(False, item.proposed_action, self.reports[item.report_id])
                store.save(self)
                return item
            if item.not_before and self.now() < datetime.fromisoformat(item.not_before):
                raise ValueError(f"Cooling-off period: this cannot be approved before {item.not_before}")
            item.status = "APPROVED"
            if item.proposed_action is not None:
                incident = self.incidents[item.incident_id]
                record = execute_approved(item.proposed_action, incident, self.reports[item.report_id])
                incident.actions.append(record)
                self.decisions[item.report_id].trace.append(
                    f"Review {review_id}: {record.action.type.value} → {record.outcome.value} ({record.detail})")
                if record.outcome is ActionOutcome.FAILED:
                    item.status = "APPROVED_ACTION_FAILED"
                elif not self._pending(incident.incident_id):
                    target = STATE_AFTER_APPROVED.get(record.action.type, IncidentState.INVESTIGATING)
                    incident.status = transition_state(incident.status, target)
            store.save(self)
            return item

    def move_state(self, incident_id: str, target: IncidentState) -> IncidentRecord:
        with self.lock:
            incident = self.incidents[incident_id]
            if self._pending(incident_id):
                raise ValueError("Resolve pending reviews before moving state")
            next_state = transition_state(incident.status, target)
            if next_state is IncidentState.PENDING_REVIEW and target is not IncidentState.PENDING_REVIEW:
                raise ValueError("Requested transition is illegal")
            incident.status = next_state
            store.save(self)
            return incident

    def snapshot(self) -> dict:
        with self.lock:
            return {"reports": list(self.reports.values()), "incidents": list(self.incidents.values()),
                    "decisions": list(self.decisions.values()), "reviews": list(self.reviews.values()),
                    "replay": {"total": len(self.queue), "position": self.position}}
