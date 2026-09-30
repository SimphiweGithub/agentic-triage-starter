"""KinGuard vocabulary: every label the agent is allowed to use."""
from enum import Enum


class IncidentState(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    PENDING_REVIEW = "PENDING_REVIEW"
    CONTAINED = "CONTAINED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SeverityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionType(str, Enum):
    RECORD_ONLY = "RECORD_ONLY"
    WARN_PERSON = "WARN_PERSON"
    FLAG_SENDER = "FLAG_SENDER"
    DRAFT_DISPUTE = "DRAFT_DISPUTE"
    BLOCK_OPERATOR = "BLOCK_OPERATOR"
    WITHDRAW = "WITHDRAW"


class ServiceDomain(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    PERSON = "PERSON"
    MAIL_FILTER = "MAIL_FILTER"
    BANK = "BANK"


class Relationship(str, Enum):
    NEW = "NEW"
    RELATED = "RELATED"
    DUPLICATE = "DUPLICATE"


class ActionOutcome(str, Enum):
    """What the runtime did with a proposal."""
    NONE = "NONE"
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    HELD_FOR_REVIEW = "HELD_FOR_REVIEW"
    SUPPRESSED_DUPLICATE = "SUPPRESSED_DUPLICATE"
    SUPPRESSED_REPEAT = "SUPPRESSED_REPEAT"


class ThreatDomain(str, Enum):
    BENIGN = "BENIGN"
    GREY_MARKET_SUBSCRIPTION = "GREY_MARKET_SUBSCRIPTION"
    IDENTITY_FARMING = "IDENTITY_FARMING"
    TECH_SUPPORT_SCAM = "TECH_SUPPORT_SCAM"
    PRIZE_SCAM = "PRIZE_SCAM"
    UNKNOWN = "UNKNOWN"
