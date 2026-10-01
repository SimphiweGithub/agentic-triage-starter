"""Scam Stop rules: what may happen automatically, what needs the caregiver, what never happens."""
from domain.enums import ActionType, IncidentState, ServiceDomain, SeverityLevel

ALLOWED_TRANSITIONS: dict[IncidentState, set[IncidentState]] = {
    IncidentState.NEW: {IncidentState.TRIAGED, IncidentState.INVESTIGATING, IncidentState.CONTAINED, IncidentState.PENDING_REVIEW},
    IncidentState.TRIAGED: {IncidentState.INVESTIGATING, IncidentState.CONTAINED, IncidentState.RESOLVED, IncidentState.PENDING_REVIEW},
    IncidentState.INVESTIGATING: {IncidentState.TRIAGED, IncidentState.CONTAINED, IncidentState.RESOLVED, IncidentState.PENDING_REVIEW},
    IncidentState.CONTAINED: {IncidentState.INVESTIGATING, IncidentState.RESOLVED, IncidentState.PENDING_REVIEW},
    IncidentState.PENDING_REVIEW: {IncidentState.INVESTIGATING, IncidentState.CONTAINED, IncidentState.RESOLVED, IncidentState.CLOSED},
    IncidentState.RESOLVED: {IncidentState.CLOSED, IncidentState.INVESTIGATING, IncidentState.PENDING_REVIEW},
    IncidentState.CLOSED: set(),
}

MIN_AUTOMATION_CONFIDENCE = 0.75
# No action type moves money, so nothing is forbidden outright; add any such action here.
FORBIDDEN_ACTIONS: set[ActionType] = set()
# These act on the person's bank relationship or set a standing rule on their mailbox, so the caregiver approves every one.
HIGH_IMPACT_ACTIONS: set[ActionType] = {ActionType.DRAFT_DISPUTE, ActionType.BLOCK_OPERATOR, ActionType.FILTER_SENDER}
# Reversible and low consequence: may run without a human when confidence is high enough.
SAFE_ACTIONS: set[ActionType] = {ActionType.RECORD_ONLY, ActionType.WARN_PERSON, ActionType.ADVISE_DECLINE, ActionType.FLAG_SENDER, ActionType.WITHDRAW}
ALLOWED_SERVICE_ACTIONS: dict[ServiceDomain, set[ActionType]] = {
    ServiceDomain.UNSPECIFIED: {ActionType.RECORD_ONLY},
    ServiceDomain.PERSON: {ActionType.WARN_PERSON, ActionType.ADVISE_DECLINE},
    ServiceDomain.MAIL_FILTER: {ActionType.FLAG_SENDER, ActionType.FILTER_SENDER},
    ServiceDomain.BANK: {ActionType.DRAFT_DISPUTE, ActionType.BLOCK_OPERATOR, ActionType.WITHDRAW},
}

# Merge guard. Identical text is a duplicate only with a second signal: the same
# context key, or timestamps within this window. Reports whose context keys are
# both known and different are never merged by the fuzzy tier.
DUPLICATE_WINDOW_SECONDS = 3600

# Sticky review. Once an incident triggers review, later reports stay flagged
# while its assessed severity is in this set (see domain.logic.risk_persists).
REVIEW_HOLD_SEVERITIES: set[SeverityLevel] = {SeverityLevel.HIGH, SeverityLevel.CRITICAL}

# An action already taken for an incident is not taken again unless listed here.
REPEATABLE_ACTIONS: set[ActionType] = set()
# For these actions, a different value of the named detail makes it a different action, not a repeat.
ACTION_IDENTITY: dict[ActionType, str] = {ActionType.FLAG_SENDER: "target", ActionType.FILTER_SENDER: "target"}

# Correction loop. After a tool fails, the agent may try this many corrected actions before asking a human.
MAX_CORRECTIONS = 2
# State an incident moves to when a human-approved action of each type runs successfully.
STATE_AFTER_APPROVED: dict[ActionType, IncidentState] = {
    ActionType.DRAFT_DISPUTE: IncidentState.CONTAINED,
    ActionType.BLOCK_OPERATOR: IncidentState.CONTAINED,
    ActionType.FILTER_SENDER: IncidentState.CONTAINED,
    ActionType.WITHDRAW: IncidentState.RESOLVED,
}

# When one of these actions runs, reviews still waiting on the same incident are closed as superseded.
SUPERSEDING_ACTIONS: set[ActionType] = {ActionType.WITHDRAW}

# Gate. A message scoring below this is logged as benign and not investigated.
GATE_THRESHOLD = 0.3
# The decision model's probability must reach this for its answer to count as a yes.
MODEL_YES = 0.7
# The decision model's threat type is used only at or above this confidence.
MODEL_THREAT_CONFIDENCE = 0.6
# Risk at or above this earns containment (flagging the sender) rather than only a warning.
CONTAIN_THRESHOLD = 0.6
# A suspicious debit at or above this amount in rand is HIGH severity.
HIGH_AMOUNT = 300.0
# Registered more recently than this many days counts as newly created.
YOUNG_DAYS = 90
# A debit this many times larger than the last one from the same merchant is a price jump.
JUMP_RATIO = 2.0
# A shortened merchant name must be at least this similar to a registered name to count as the same company.
NAME_SIMILARITY = 0.6

# An unauthorised debit can be disputed with the bank for this many days after it runs.
DISPUTE_WINDOW_DAYS = 60
# With no guardian enrolled, a person who confirms a high-risk sender must wait this long before it takes effect.
COOLING_OFF_SECONDS = 24 * 60 * 60

# Shared mail providers. Flagging one of these domains would block legitimate senders,
# so the mail filter refuses and the agent must narrow the flag to a single address.
PROTECTED_DOMAINS: set[str] = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"}
