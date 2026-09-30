"""The tools the agent calls, and the outside world they read or change.

Domain age can be looked up for real (see `domain_age`). The bank, the company
registry and the mail filter are simulated: they keep the shape a real
integration would have (typed input, a ToolResult that says whether it
worked) but act on the in-memory `WORLD` and fixture data below.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from typing import Callable
import urllib.request

from domain.enums import ActionOutcome, ActionType
from domain.extract import normalise_name
from domain.policy import PROTECTED_DOMAINS
from domain.schemas import ActionProposal, IncidentRecord, RawInputReport, ToolResult


@dataclass
class World:
    outbox: list[dict] = field(default_factory=list)           # messages shown to the protected person
    flagged: set[str] = field(default_factory=set)             # senders and domains the mail filter blocks
    disputes: dict[str, str] = field(default_factory=dict)     # company registration number -> dispute text
    blocked: set[str] = field(default_factory=set)             # operators whose debits the bank is asked to refuse
    trusted: set[str] = field(default_factory=set)             # merchants the person confirmed as their own
    debits: dict[str, list[float]] = field(default_factory=dict)  # merchant -> amounts seen so far


WORLD = World()


def reset_world() -> None:
    WORLD.__init__()


# Fixture data standing in for registries we cannot query. All names and domains are fictional.
DOMAIN_REGISTERED = {
    "techcare-help.example": "2026-09-27",
    "streambox.example": "2012-05-01",
}
# creditor_code: the short code a company's debit references start with.
# director: the person registered as controlling the company.
COMPANIES = [
    {"name": "TechCare Support", "reg_no": "2026/118822/07", "registered": "2026-08-20", "creditor_code": "TCS", "director": "D-7781"},
    {"name": "TechCare Solutions", "reg_no": "2011/004411/07", "registered": "2011-03-02", "creditor_code": "TSO", "director": "D-1020"},
    {"name": "PC Care Services", "reg_no": "2026/120001/07", "registered": "2026-10-20", "creditor_code": "PCC", "director": "D-7781"},
    {"name": "StreamBox", "reg_no": "2009/030303/07", "registered": "2009-06-15", "creditor_code": "SBX", "director": "D-3344"},
]


def _days_between(registered: datetime, when: datetime) -> int:
    return (when - registered).days


def _parse_date(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---- investigation tools: read only ----

def _live_registration(domain: str) -> datetime | None:
    """Ask the public registration-data service (RDAP) when a domain was registered. Only the domain name is sent."""
    labels = domain.split(".")
    for start in range(max(len(labels) - 1, 1)):  # try the full name, then drop leading labels (mail.shop.example -> shop.example)
        request = urllib.request.Request(f"https://rdap.org/domain/{'.'.join(labels[start:])}",
                                         headers={"Accept": "application/rdap+json", "User-Agent": "KinGuard/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=6) as response:
                events = json.load(response).get("events", [])
        except (OSError, ValueError):  # network failure, not found, or an unreadable reply
            continue
        for event in events:
            if event.get("eventAction") == "registration":
                return _parse_date(event["eventDate"])
    return None


def domain_age(domain: str, when: datetime) -> ToolResult:
    registered, source = None, "fixture"
    if os.getenv("KINGUARD_LIVE_LOOKUPS") == "1":
        registered, source = _live_registration(domain), "live lookup"
    if registered is None and domain in DOMAIN_REGISTERED:  # live lookup off, failed, or had no record: fall back
        registered, source = _parse_date(DOMAIN_REGISTERED[domain]), "fixture"
    if registered is None:
        return ToolResult(ok=False, detail=f"no registration record for {domain}")
    days = _days_between(registered, when)
    return ToolResult(ok=True, detail=f"{domain} was registered {days} days before the message ({source})", data={"age_days": days})


def merchant_registry(name: str, reference: str = "", when: datetime | None = None) -> ToolResult:
    words = set(normalise_name(name).split())
    matches = [company for company in COMPANIES if words and words <= set(normalise_name(company["name"]).split())]
    if reference:
        matches = [company for company in matches if reference.startswith(company["creditor_code"])]
    if not matches:
        return ToolResult(ok=False, detail=f"no registered company matches '{name}'")
    if len(matches) > 1:
        names = ", ".join(company["name"] for company in matches)
        return ToolResult(ok=False, detail=f"'{name}' is ambiguous: {names}", data={"candidates": len(matches)})
    company = dict(matches[0])
    company["age_days"] = _days_between(_parse_date(company["registered"]), when or datetime.now(timezone.utc))
    return ToolResult(ok=True, detail=f"{company['name']} ({company['reg_no']}), registered {company['age_days']} days before the message", data=company)


def identify_operator(merchant: str, reference: str) -> str:
    """The director behind a merchant, or "" if the registry cannot say. Two company names with one director are one operator."""
    result = merchant_registry(merchant)
    if not result.ok and reference:
        result = merchant_registry(merchant, reference)
    return result.data.get("director", "") if result.ok else ""


def mandate_history(merchant: str, amount: float) -> ToolResult:
    previous = WORLD.debits.get(merchant, [])
    ratio = round(amount / previous[-1], 2) if previous and previous[-1] else None
    detail = f"first debit seen from '{merchant}'" if not previous else f"previous debit was R{previous[-1]:.2f}; this one is {ratio}x"
    return ToolResult(ok=True, detail=detail, data={"first_time": not previous, "ratio": ratio})


# ---- action tools: change the world ----

def warn_person(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult:
    WORLD.outbox.append({"incident_id": incident.incident_id, "message": action.details.get("message", "")})
    return ToolResult(ok=True, detail="warning delivered to the person")


def flag_sender(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult:
    target = str(action.details.get("target") or "")
    if not target:
        return ToolResult(ok=False, detail="no sender to flag")
    if target in PROTECTED_DOMAINS:
        return ToolResult(ok=False, detail=f"{target} is a shared mail provider; flagging the whole domain is refused", data={"protected": True})
    WORLD.flagged.add(target)
    WORLD.outbox.append({"incident_id": incident.incident_id, "message": action.details.get("message", "")})
    return ToolResult(ok=True, detail=f"{target} added to the sender blocklist; person warned")


def draft_dispute(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult:
    reg_no = action.details.get("reg_no")
    if not reg_no:
        return ToolResult(ok=False, detail="merchant identity unresolved; a dispute cannot be addressed")
    text = (f"I dispute the debit of R{action.details.get('amount', 0):.2f} by {action.details.get('company')} "
            f"({reg_no}), reference {action.details.get('reference') or 'not shown'}. I did not authorise this mandate.")
    WORLD.disputes[reg_no] = text
    return ToolResult(ok=True, detail=f"dispute drafted against {action.details.get('company')}", data={"text": text})


def block_operator(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult:
    operator = str(action.details.get("operator") or "")
    if not operator:
        return ToolResult(ok=False, detail="operator not identified; nothing to block")
    WORLD.blocked.add(operator)
    names = ", ".join(company["name"] for company in COMPANIES if company["director"] == operator)
    return ToolResult(ok=True, detail=f"bank asked to refuse all mandates from operator {operator} ({names})")


def withdraw(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult:
    """Undo what was done for this incident and remember the merchant as trusted."""
    undone = []
    for record in incident.actions:
        if record.outcome is not ActionOutcome.EXECUTED:
            continue
        if record.action.type is ActionType.FLAG_SENDER:
            WORLD.flagged.discard(record.action.details.get("target"))
            undone.append("sender flag removed")
        elif record.action.type is ActionType.DRAFT_DISPUTE:
            WORLD.disputes.pop(record.action.details.get("reg_no"), None)
            undone.append("dispute withdrawn")
    merchant = str(action.details.get("merchant") or "")
    if merchant:
        WORLD.trusted.add(merchant)
        undone.append(f"'{merchant}' remembered as trusted")
    return ToolResult(ok=True, detail="; ".join(undone) or "nothing to undo")


ActionTool = Callable[[ActionProposal, IncidentRecord, RawInputReport], ToolResult]
ACTION_TOOLS: dict[ActionType, ActionTool] = {
    ActionType.WARN_PERSON: warn_person,
    ActionType.FLAG_SENDER: flag_sender,
    ActionType.DRAFT_DISPUTE: draft_dispute,
    ActionType.BLOCK_OPERATOR: block_operator,
    ActionType.WITHDRAW: withdraw,
}


def correct(action: ActionProposal, result: ToolResult, report: RawInputReport) -> ActionProposal | None:
    """Given a failed action, return a corrected one to try next, or None to hand over to a human."""
    sender = (report.metadata.get("signals") or {}).get("sender", "")
    if action.type is ActionType.FLAG_SENDER and result.data.get("protected") and sender and action.details.get("target") != sender:
        return action.model_copy(update={"details": {**action.details, "target": sender}})
    return None
