"""Challenge swap point: lifecycle graph and action registries."""
from domain.enums import ActionType, IncidentState, ServiceDomain

ALLOWED_TRANSITIONS: dict[IncidentState, set[IncidentState]] = {
    IncidentState.NEW: {IncidentState.TRIAGED, IncidentState.PENDING_REVIEW},
    IncidentState.TRIAGED: {IncidentState.INVESTIGATING, IncidentState.PENDING_REVIEW},
    IncidentState.INVESTIGATING: {IncidentState.RESOLVED, IncidentState.PENDING_REVIEW},
    IncidentState.PENDING_REVIEW: {IncidentState.INVESTIGATING, IncidentState.RESOLVED, IncidentState.CLOSED},
    IncidentState.RESOLVED: {IncidentState.CLOSED, IncidentState.INVESTIGATING, IncidentState.PENDING_REVIEW},
    IncidentState.CLOSED: set(),
}

MIN_AUTOMATION_CONFIDENCE = 0.75
FORBIDDEN_ACTIONS: set[ActionType] = set()
HIGH_IMPACT_ACTIONS: set[ActionType] = set()
SAFE_ACTIONS: set[ActionType] = {ActionType.RECORD_ONLY}
ALLOWED_SERVICE_ACTIONS: dict[ServiceDomain, set[ActionType]] = {
    ServiceDomain.UNSPECIFIED: {ActionType.RECORD_ONLY},
}
