"""Policy interceptor. Proposals are never executed by this module."""
from dataclasses import dataclass

from domain.policy import ALLOWED_SERVICE_ACTIONS, FORBIDDEN_ACTIONS, HIGH_IMPACT_ACTIONS, MIN_AUTOMATION_CONFIDENCE, SAFE_ACTIONS
from domain.schemas import ActionProposal


@dataclass(frozen=True)
class SafetyDecision:
    requires_review: bool
    reason: str


def enforce_action_safety(action: ActionProposal | None, confidence: float) -> SafetyDecision:
    if action is None:
        return SafetyDecision(False, "No action proposed")
    if action.type in FORBIDDEN_ACTIONS:
        return SafetyDecision(True, "Forbidden action; manual handling only")
    if action.type not in ALLOWED_SERVICE_ACTIONS.get(action.service, set()):
        return SafetyDecision(True, "Action is invalid for the selected service")
    if confidence < MIN_AUTOMATION_CONFIDENCE:
        return SafetyDecision(True, f"Confidence below {MIN_AUTOMATION_CONFIDENCE:.2f}")
    if action.type in HIGH_IMPACT_ACTIONS:
        return SafetyDecision(True, "High impact action requires approval")
    if action.type not in SAFE_ACTIONS:
        return SafetyDecision(True, "Action has no automation allowlist entry")
    return SafetyDecision(False, "Allowed by policy")
