"""Correlation in tiers: explicit link, shared identifiers, then fuzzy text with a merge guard."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Callable

from domain.enums import Relationship
from domain.logic import context_key, correlation_text, link_keys, parse_timestamp
from domain.policy import DUPLICATE_WINDOW_SECONDS
from domain.schemas import IncidentRecord, RawInputReport


def _normalise(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _score(left: str, right: str) -> float:
    a, b = _normalise(left), _normalise(right)
    if not a or not b:
        return 0.0
    token_a, token_b = set(a.split()), set(b.split())
    jaccard = len(token_a & token_b) / len(token_a | token_b)
    return 0.6 * jaccard + 0.4 * SequenceMatcher(None, a, b).ratio()


def _context_conflict(left: RawInputReport, right: RawInputReport) -> bool:
    a, b = context_key(left), context_key(right)
    return bool(a and b and a != b)


def _second_signal(report: RawInputReport, prior: RawInputReport) -> str | None:
    """A reason, beyond matching text, to believe two reports describe the same occurrence."""
    new_time, prior_time = parse_timestamp(report.timestamp), parse_timestamp(prior.timestamp)
    if new_time and prior_time:  # when both times are known, time decides: a repeat next month is a new event
        within = abs((new_time - prior_time).total_seconds()) <= DUPLICATE_WINDOW_SECONDS
        return "within time window" if within else None
    key = context_key(report)
    if key and key == context_key(prior):
        return "same context"
    return None


@dataclass(frozen=True)
class Correlation:
    incident_id: str | None
    relationship: Relationship
    score: float
    reason: str = ""


RelationResolver = Callable[[RawInputReport, IncidentRecord, list[RawInputReport]], Relationship]


class Correlator:
    def __init__(self, relation_resolver: RelationResolver | None = None, candidate_threshold: float = 0.55):
        self.relation_resolver = relation_resolver
        self.candidate_threshold = candidate_threshold

    def _linked(self, report: RawInputReport, incidents: dict[str, IncidentRecord], reports: dict[str, RawInputReport]) -> tuple[str, str] | None:
        """Tiers one and two: an explicit incident link, or an identifier shared with an earlier report."""
        explicit = report.metadata.get("incident_id")
        if explicit in incidents:
            return explicit, "Explicit link to the incident"
        keys = link_keys(report)
        if keys:
            for incident_id in reversed(list(incidents)):  # most recent incident first
                for report_id in incidents[incident_id].report_ids:
                    shared = keys & link_keys(reports[report_id])
                    if shared:
                        return incident_id, f"Shared identifier {sorted(shared)[0]}"
        return None

    def match(self, report: RawInputReport, incidents: dict[str, IncidentRecord], reports: dict[str, RawInputReport]) -> Correlation:
        incoming = correlation_text(report)
        linked = self._linked(report, incidents, reports)
        notes = []
        if linked:
            best_id, best_score = linked[0], 1.0
            notes.append(linked[1])
        else:
            best_id, best_score, blocked_id, blocked_score = None, 0.0, None, 0.0
            for incident_id, incident in incidents.items():
                for report_id in incident.report_ids:
                    prior = reports[report_id]
                    score = _score(incoming, correlation_text(prior))
                    if _context_conflict(report, prior):
                        if score > blocked_score:
                            blocked_id, blocked_score = incident_id, score
                    elif score and score >= best_score:  # ties go to the most recent incident
                        best_id, best_score = incident_id, score
            if best_id is None or best_score < self.candidate_threshold:
                reason = "No candidate above threshold"
                if blocked_id and blocked_score >= self.candidate_threshold:
                    reason = f"Text matches {blocked_id} ({blocked_score:.3f}) but context differs; kept separate"
                return Correlation(None, Relationship.NEW, round(best_score, 3), reason)

        incident = incidents[best_id]
        history = [reports[report_id] for report_id in incident.report_ids]
        relation = None
        if self.relation_resolver and not linked:
            try:
                relation = self.relation_resolver(report, incident, history)
                if relation not in (Relationship.NEW, Relationship.RELATED, Relationship.DUPLICATE):
                    raise ValueError("unsupported label")
                notes.append("Relation resolver")
            except Exception as error:  # a model failure must not stop the run
                relation = None
                notes.append(f"Relation resolver unavailable ({type(error).__name__}); deterministic fallback")
        fuzzy = relation is None
        if fuzzy:
            identical = any(_normalise(incoming) == _normalise(correlation_text(prior))
                            for prior in history if not _context_conflict(report, prior))
            relation = Relationship.DUPLICATE if identical else Relationship.RELATED
            if not linked:
                notes.append("Fuzzy match")
        if relation is Relationship.NEW:
            return Correlation(None, Relationship.NEW, round(best_score, 3), "; ".join(notes + ["resolver judged it a new incident"]))
        if relation is Relationship.DUPLICATE:
            signal = next((found for prior in history if not _context_conflict(report, prior)
                           and (found := _second_signal(report, prior))), None)
            if signal:
                notes.append(f"duplicate confirmed by {signal}")
            elif (fuzzy and not linked and not any(context_key(report) and context_key(report) == context_key(prior) for prior in history)
                  and parse_timestamp(report.timestamp) and all(parse_timestamp(prior.timestamp) for prior in history)):
                # Text is the only evidence and every known time is outside the window: a new occurrence.
                return Correlation(None, Relationship.NEW, round(best_score, 3),
                                   f"Text matches {best_id} but it is outside the duplicate window with no shared context; kept separate")
            else:
                relation = Relationship.RELATED
                notes.append("matching text but no second signal; not treated as a duplicate")
        return Correlation(best_id, relation, round(best_score, 3), "; ".join(notes))
