"""Two-tier correlation: cheap candidate search, optional relation resolver."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Callable

from domain.enums import Relationship
from domain.logic import correlation_text
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


@dataclass(frozen=True)
class Correlation:
    incident_id: str | None
    relationship: Relationship
    score: float


RelationResolver = Callable[[RawInputReport, IncidentRecord, list[RawInputReport]], Relationship]


class Correlator:
    def __init__(self, relation_resolver: RelationResolver | None = None, candidate_threshold: float = 0.55):
        self.relation_resolver = relation_resolver
        self.candidate_threshold = candidate_threshold

    def match(self, report: RawInputReport, incidents: dict[str, IncidentRecord], reports: dict[str, RawInputReport]) -> Correlation:
        best_id, best_score = None, 0.0
        incoming = correlation_text(report)
        for incident_id, incident in incidents.items():
            score = max((_score(incoming, correlation_text(reports[report_id])) for report_id in incident.report_ids), default=0.0)
            if score > best_score:
                best_id, best_score = incident_id, score
        if best_id is None or best_score < self.candidate_threshold:
            return Correlation(None, Relationship.NEW, round(best_score, 3))
        incident = incidents[best_id]
        if self.relation_resolver:
            relation = self.relation_resolver(report, incident, [reports[report_id] for report_id in incident.report_ids])
            if relation is Relationship.NEW:
                return Correlation(None, Relationship.NEW, round(best_score, 3))
            if relation not in (Relationship.RELATED, Relationship.DUPLICATE):
                raise ValueError("Relation resolver returned an unsupported label")
        else:
            relation = Relationship.DUPLICATE if any(_normalise(incoming) == _normalise(correlation_text(reports[report_id]))
                for report_id in incident.report_ids) else Relationship.RELATED
        return Correlation(best_id, relation, round(best_score, 3))
