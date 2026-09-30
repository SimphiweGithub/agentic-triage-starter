"""Replace placeholders with the judge supplied ontology."""
from enum import Enum


class IncidentState(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    PENDING_REVIEW = "PENDING_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SeverityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionType(str, Enum):
    RECORD_ONLY = "RECORD_ONLY"


class ServiceDomain(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"


class Relationship(str, Enum):
    NEW = "NEW"
    RELATED = "RELATED"
    DUPLICATE = "DUPLICATE"
