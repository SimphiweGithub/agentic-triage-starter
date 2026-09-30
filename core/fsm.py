"""Strict state transitions; model suggestions are never authoritative."""
from domain.enums import IncidentState
from domain.policy import ALLOWED_TRANSITIONS


def transition_state(current: IncidentState, target: IncidentState) -> IncidentState:
    if target == current or target in ALLOWED_TRANSITIONS.get(current, set()):
        return target
    return IncidentState.PENDING_REVIEW
