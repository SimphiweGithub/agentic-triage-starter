"""The tools the agent calls, and the outside world they read or change.

Domain age can be looked up for real (see `domain_age`). The person's own
mailbox is changed for real when the server has registered one (see
`set_mailbox`): a flagged email goes to the Bin, and an approved filter sends a
sender's later mail there too. The bank and the company registry are
simulated: they keep the shape a real integration would have (typed input, a
ToolResult that says whether it worked) but act on the in-memory `WORLD` and
fixture data below.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import os
import re
from typing import Callable, Protocol
import urllib.request

from domain.enums import ActionOutcome, ActionType
from domain.extract import normalise_name
from domain.policy import NAME_SIMILARITY, PROTECTED_DOMAINS
from domain.schemas import ActionProposal, IncidentRecord, RawInputReport, ToolResult


@dataclass
class World:
    outbox: list[dict] = field(default_factory=list)           # messages shown to the protected person
    flagged: set[str] = field(default_factory=set)             # senders and domains the mail filter blocks
    disputes: dict[str, dict] = field(default_factory=dict)    # company registration number -> dispute text, deadline, steps
    blocked: set[str] = field(default_factory=set)             # operators whose debits the bank is asked to refuse
    trusted: set[str] = field(default_factory=set)             # merchants the person confirmed as their own
    known_senders: set[str] = field(default_factory=set)       # senders a human said were fine when a doubtful warning was held
    debits: dict[str, list[float]] = field(default_factory=dict)  # merchant -> amounts seen so far
    binned: dict[str, dict] = field(default_factory=dict)      # "<action>:<report id>" -> what was moved to the Bin, so it can be undone
    guardian: bool = field(default_factory=lambda: os.getenv("KINGUARD_GUARDIAN", "1") != "0")  # is a caregiver enrolled?


_default_world = World()
_active_world: ContextVar[World] = ContextVar("active_world", default=_default_world)


class _ActiveWorld:
    """`WORLD` for the domain code. It always means the world of the person being worked on.

    Each person's runtime activates its own world while it processes anything, so the rules and
    tools below never need to be told whose world they are in. Used on its own, it is the shared default.
    """

    def __getattr__(self, name):
        return getattr(_active_world.get(), name)

    def __setattr__(self, name, value):
        setattr(_active_world.get(), name, value)


WORLD = _ActiveWorld()


def default_world() -> World:
    """The shared world used when nobody asks for their own (the plain console, offline runs, tests)."""
    return _default_world


@contextmanager
def use_world(world: World):
    """Make `world` the one `WORLD` means, for everything run inside the block."""
    token = _active_world.set(world)
    try:
        yield
    finally:
        _active_world.reset(token)


def reset_world() -> None:
    """Empty the active world."""
    _active_world.get().__init__()


def world_state() -> dict:
    """The world as plain JSON values, for saving to disk. Sets become sorted lists."""
    return {"outbox": WORLD.outbox, "flagged": sorted(WORLD.flagged), "disputes": WORLD.disputes,
            "blocked": sorted(WORLD.blocked), "trusted": sorted(WORLD.trusted), "debits": WORLD.debits,
            "known_senders": sorted(WORLD.known_senders), "binned": WORLD.binned,
            "guardian": WORLD.guardian}


def restore_world(saved: dict) -> None:
    """Put a saved world back."""
    reset_world()  # WORLD is a proxy for the active world, so its own __init__ would reset nothing
    WORLD.outbox, WORLD.disputes, WORLD.debits = saved["outbox"], saved["disputes"], saved["debits"]
    WORLD.flagged, WORLD.blocked, WORLD.trusted = set(saved["flagged"]), set(saved["blocked"]), set(saved["trusted"])
    WORLD.known_senders = set(saved.get("known_senders", []))  # older saved files do not have it
    WORLD.binned = saved.get("binned", {})
    WORLD.guardian = saved["guardian"]


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


# How a person lodges a dispute. General steps; each bank's own screens differ.
DISPUTE_STEPS = [
    "Open your banking app, or visit a branch with your ID.",
    "Find the debit order in your transaction history.",
    "Choose to dispute it and select that you did not authorise it.",
    "Keep the reference number the bank gives you.",
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
                                         headers={"Accept": "application/rdap+json", "User-Agent": "Scam Stop/0.1"})
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


def _similarity(left: str, right: str) -> float:
    """How alike two names are, from 0 to 1, ignoring case, spaces and punctuation."""
    return SequenceMatcher(None, normalise_name(left).replace(" ", ""), normalise_name(right).replace(" ", "")).ratio()


def merchant_registry(name: str, reference: str = "", when: datetime | None = None) -> ToolResult:
    words = set(normalise_name(name).split())
    matches = [company for company in COMPANIES if words and words <= set(normalise_name(company["name"]).split())]
    if reference:
        matches = [company for company in matches if reference.startswith(company["creditor_code"])]
    if not matches and reference:
        # Banks shorten and garble merchant names. Find the company by the creditor code in the reference,
        # and accept it only if the garbled name is close enough to the registered one.
        matches = [company for company in COMPANIES if reference.startswith(company["creditor_code"])
                   and _similarity(name, company["name"]) >= NAME_SIMILARITY]
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


# ---- the person's mailbox ----

class MailboxError(Exception):
    """The mailbox refused or could not be reached. The message says why, in plain words."""


class Mailbox(Protocol):
    """What the tools may do to a connected mailbox. The server registers the real one; tests register a stand-in."""
    def trash(self, mailbox_id: str, message_ids: list[str]) -> list[str]: ...   # returns the ids actually moved
    def untrash(self, mailbox_id: str, message_ids: list[str]) -> None: ...
    def find_from(self, mailbox_id: str, sender: str) -> list[str]: ...
    def add_filter(self, mailbox_id: str, sender: str) -> tuple[str, bool]: ...  # (filter id, whether it was created now)
    def remove_filter(self, mailbox_id: str, filter_id: str) -> None: ...


_mailbox: Mailbox | None = None
SINGLE_ADDRESS = re.compile(r"[^@\s\"(),:;<>\[\]]+@[a-z0-9.-]+\.[a-z]{2,}")


def set_mailbox(mailbox: Mailbox | None) -> None:
    """Register how to reach connected mailboxes. Without one, flagging still works and nothing is moved."""
    global _mailbox
    _mailbox = mailbox


def is_single_address(text: str) -> bool:
    """One exact email address, not a domain: the only thing a standing filter may match."""
    return bool(SINGLE_ADDRESS.fullmatch(text or ""))


def _bin_reported_email(report: RawInputReport, target: str) -> bool:
    """Move the email itself to the Bin when it came from a connected mailbox. Returns whether it moved."""
    mailbox, message = report.metadata.get("mailbox"), report.metadata.get("gmail_id")
    if _mailbox is None or not mailbox or not message:
        return False
    try:
        moved = _mailbox.trash(mailbox, [message])
    except MailboxError:
        return False  # the sender is still marked; the email simply stays where it is
    if moved:
        WORLD.binned[f"{ActionType.FLAG_SENDER.value}:{report.report_id}"] = {"mailbox": mailbox, "target": target, "messages": moved}
    return bool(moved)


def _restore(entry: dict) -> list[str]:
    """Undo what was moved to the Bin, and remove a filter Scam Stop created. Returns what was undone."""
    if _mailbox is None:
        return ["the mailbox could not be reached to undo the Bin"]
    undone = []
    try:
        if entry.get("messages"):
            _mailbox.untrash(entry["mailbox"], entry["messages"])
            undone.append(f"{len(entry['messages'])} email(s) taken out of the Bin")
        if entry.get("filter_id") and entry.get("created"):
            _mailbox.remove_filter(entry["mailbox"], entry["filter_id"])
            undone.append(f"filter for {entry['target']} removed")
    except MailboxError as error:
        undone.append(f"the mailbox could not be fully restored ({error})")
    return undone


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
    binned = _bin_reported_email(report, target)
    message = action.details.get("message", "")
    if binned:  # only said when it is true
        message += " We have moved this email to your Bin. You can still find it there for 30 days."
    WORLD.outbox.append({"incident_id": incident.incident_id, "message": message})
    return ToolResult(ok=True, detail=f"{target} marked as a scammer; later messages from them are treated as high risk; "
                                      + ("email moved to the Bin; " if binned else "") + "person warned")


def filter_sender(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult:
    """Send every later email from one address straight to the Bin, and move the earlier ones there too."""
    target, mailbox = str(action.details.get("target") or "").lower(), str(action.details.get("mailbox") or "")
    if not is_single_address(target):
        return ToolResult(ok=False, detail="only a single email address can be sent to the Bin, never a whole domain")
    if not mailbox or _mailbox is None:
        return ToolResult(ok=False, detail="this sender did not write to a connected mailbox, so there is nothing to filter")
    try:
        filter_id, created = _mailbox.add_filter(mailbox, target)
    except MailboxError as error:
        return ToolResult(ok=False, detail=f"the filter could not be made: {error}")
    entry = {"mailbox": mailbox, "target": target, "filter_id": filter_id, "created": created, "messages": []}
    WORLD.binned[f"{ActionType.FILTER_SENDER.value}:{report.report_id}"] = entry
    try:
        entry["messages"] = _mailbox.trash(mailbox, _mailbox.find_from(mailbox, target))
    except MailboxError as error:
        return ToolResult(ok=True, detail=f"later mail from {target} now goes to the Bin; earlier emails could not be moved ({error})")
    return ToolResult(ok=True, detail=f"later mail from {target} now goes to the Bin; {len(entry['messages'])} earlier email(s) moved to the Bin")


def draft_dispute(action: ActionProposal, incident: IncidentRecord, report: RawInputReport) -> ToolResult:
    reg_no = action.details.get("reg_no")
    if not reg_no:
        return ToolResult(ok=False, detail="merchant identity unresolved; a dispute cannot be addressed")
    text = (f"I dispute the debit of R{action.details.get('amount', 0):.2f} by {action.details.get('company')} "
            f"({reg_no}), reference {action.details.get('reference') or 'not shown'}. I did not authorise this mandate.")
    WORLD.disputes[reg_no] = {"text": text, "dispute_by": action.details.get("dispute_by", ""), "steps": DISPUTE_STEPS}
    return ToolResult(ok=True, detail=f"dispute drafted against {action.details.get('company')}; lodge by {action.details.get('dispute_by') or 'the bank deadline'}",
                      data=WORLD.disputes[reg_no])


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
        entry = WORLD.binned.pop(f"{record.action.type.value}:{record.report_id}", None)
        if entry:
            undone += _restore(entry)
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
    ActionType.ADVISE_DECLINE: warn_person,  # same delivery; the message carries the advice
    ActionType.FLAG_SENDER: flag_sender,
    ActionType.FILTER_SENDER: filter_sender,
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
