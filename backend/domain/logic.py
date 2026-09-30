"""KinGuard decisions: how a message is read, linked to an incident, and assessed."""
from datetime import datetime, timezone
import os
from typing import Any

from domain.enums import ActionOutcome, ActionType, IncidentState, ServiceDomain, SeverityLevel, ThreatDomain
from domain.extract import extract_signals, is_one_time_code, redact
from domain.gate import ask_jev, gate
from domain.investigate import investigate
from domain.language import write_person_message
from domain.policy import CONTAIN_THRESHOLD, GATE_THRESHOLD, HIGH_AMOUNT, PROTECTED_DOMAINS, REVIEW_HOLD_SEVERITIES
from domain.schemas import ActionProposal, Assessment, IncidentRecord, RawInputReport
from domain.tools import WORLD, identify_operator

TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M")


def withhold(data: dict[str, Any]) -> str | None:
    """A reason to discard a row before it is parsed or stored, or None to keep it."""
    if is_one_time_code(str(data.get("payload") or "")):
        return "one-time code; never stored or sent to a model"
    return None


def parse_record(data: dict[str, Any]) -> RawInputReport:
    """Map one input row to a report, mask account numbers, and attach the extracted signals."""
    known = set(RawInputReport.model_fields)
    record = {key: value for key, value in data.items() if key in known and value is not None}
    extras = {key: value for key, value in data.items() if key is not None and key not in known}
    if extras:
        record["metadata"] = {**extras, **(record.get("metadata") or {})}
    report = RawInputReport.model_validate(record)
    report.payload = redact(report.payload)
    signals = extract_signals(report.payload, report.metadata)
    signals["operator"] = identify_operator(signals["merchant"], signals["reference"])
    report.metadata["signals"] = signals
    return report


def _signals(report: RawInputReport) -> dict[str, Any]:
    return report.metadata.get("signals") or extract_signals(report.payload, report.metadata)


def correlation_text(report: RawInputReport) -> str:
    return f"{report.source} {report.payload}".strip()


def context_key(report: RawInputReport) -> str:
    """Second merge signal for the fuzzy tier: who the message is about."""
    signals = _signals(report)
    key = report.metadata.get("context") or signals["merchant"] or signals["sender_domain"]
    return " ".join(str(key or "").lower().split())


def link_keys(report: RawInputReport) -> set[str]:
    """Identifiers that tie messages to the same operator even when the wording and name change."""
    signals = _signals(report)
    keys = {f"merchant:{signals['merchant']}"} if signals["merchant"] else set()
    if signals["reference"]:
        keys.add(f"ref:{signals['reference']}")
    if signals.get("operator"):
        keys.add(f"operator:{signals['operator']}")
    keys |= {f"phone:{phone}" for phone in signals["phones"]}
    keys |= {f"domain:{domain}" for domain in signals["domains"] if domain not in PROTECTED_DOMAINS}
    if signals["sender_domain"] in PROTECTED_DOMAINS:
        keys.add(f"sender:{signals['sender']}")
    return keys


def parse_timestamp(value: str) -> datetime | None:
    """Tolerant parse. Malformed values return None and never raise."""
    text = (value or "").strip()
    if not text:
        return None
    parsed = None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for pattern in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def risk_persists(incident: IncidentRecord, assessment: Assessment) -> bool:
    """Keeps the caregiver's review hold in place while the incident is still serious."""
    return assessment.severity in REVIEW_HOLD_SEVERITIES


def _withdrawal(incident: IncidentRecord) -> Assessment:
    """The person says the charge or sender is legitimate: undo our actions, unless the evidence was strong."""
    strong = incident.severity in REVIEW_HOLD_SEVERITIES
    action = ActionProposal(type=ActionType.WITHDRAW, service=ServiceDomain.BANK,
                            details={"merchant": incident.labels.get("merchant", "")})
    if strong:
        return Assessment(severity=incident.severity, confidence=0.5, requested_state=incident.status, proposed_action=action,
                          rationale="The person says this is legitimate, but the evidence against it was strong.",
                          review_reason="Person confirmed a high-risk sender as legitimate; check for coercion")
    return Assessment(severity=SeverityLevel.LOW, confidence=0.95, requested_state=IncidentState.RESOLVED, proposed_action=action,
                      rationale="The person confirmed this is legitimate; withdrawing our actions and trusting the merchant.",
                      labels={"threat": ThreatDomain.BENIGN.value})


def _kind_wording(standard: str) -> str:
    """Optionally let the language model reword a warning. The standard wording is used if it is off, fails, or is unsafe."""
    if os.getenv("ENABLE_GEMINI") != "1":
        return standard
    try:
        return write_person_message({"what to tell the person": standard})
    except Exception:
        return standard


def assess(report: RawInputReport, incident: IncidentRecord) -> Assessment:
    signals = _signals(report)
    if report.metadata.get("feedback") == "legitimate":
        return _withdrawal(incident)

    is_debit = signals["kind"] == "debit"
    verdict = gate(report.payload, signals, ask_jev if os.getenv("ENABLE_JEV") == "1" else None)
    findings, company = [], None
    if is_debit or verdict.score >= GATE_THRESHOLD:
        when = parse_timestamp(report.timestamp) or datetime.now(timezone.utc)
        findings, company = investigate(signals, when)
    if is_debit:
        WORLD.debits.setdefault(signals["merchant"], []).append(signals["amount"])

    price_jump = any(finding.source == "mandate_history" and finding.weight > 0.3 for finding in findings)
    trusted = signals["merchant"] in WORLD.trusted and not price_jump
    risk = 0.0 if trusted else min(1.0, verdict.score + sum(finding.weight for finding in findings))
    evidence = verdict.reasons + [finding.note for finding in findings if finding.weight > 0]
    threat = verdict.threat
    if threat is ThreatDomain.BENIGN and risk >= GATE_THRESHOLD:  # the wording was clean but the tools found risk
        threat = ThreatDomain.GREY_MARKET_SUBSCRIPTION if is_debit else ThreatDomain.UNKNOWN
    labels = {"threat": threat.value, "merchant": signals["merchant"], "reg_no": (company or {}).get("reg_no", "")}
    labels = {name: value for name, value in labels.items() if value}
    stay = IncidentState.TRIAGED if incident.status is IncidentState.NEW else incident.status

    if risk < GATE_THRESHOLD:
        reason = "merchant is trusted by the person" if trusted else "nothing suspicious found"
        return Assessment(severity=SeverityLevel.LOW, confidence=0.9, requested_state=stay, rationale=f"Benign: {reason}.",
                          labels={**labels, "threat": ThreatDomain.BENIGN.value})

    confidence = min(0.95, 0.55 + 0.1 * len(evidence))
    rationale = f"Risk {risk:.2f}. " + "; ".join(evidence + list(verdict.notes)) + "."
    conflict = verdict.score >= GATE_THRESHOLD and any(finding.reassuring for finding in findings)
    review_reason = "Evidence conflicts: suspicious wording from an established sender" if conflict else None
    disputed = any(record.action.type is ActionType.DRAFT_DISPUTE and record.outcome is ActionOutcome.EXECUTED
                   for record in incident.actions)
    shared_provider = signals["sender_domain"] in PROTECTED_DOMAINS
    who = signals["merchant"] or (signals["sender"] if shared_provider else signals["sender_domain"]) or "an unknown sender"
    severity, target_state = SeverityLevel.MEDIUM, IncidentState.CONTAINED

    if is_debit and disputed:
        severity = SeverityLevel.HIGH
        rationale = "A debit arrived after the dispute was lodged, so the dispute did not stop this operator. " + rationale
        action = ActionProposal(type=ActionType.BLOCK_OPERATOR, service=ServiceDomain.BANK, details={
            "merchant": signals["merchant"], "operator": signals.get("operator", "")})
    elif is_debit and company:
        severity = SeverityLevel.HIGH if signals["amount"] >= HIGH_AMOUNT else SeverityLevel.MEDIUM
        action = ActionProposal(type=ActionType.DRAFT_DISPUTE, service=ServiceDomain.BANK, details={
            "merchant": signals["merchant"], "company": company["name"], "reg_no": company["reg_no"],
            "amount": signals["amount"], "reference": signals["reference"]})
    elif is_debit:
        target_state = IncidentState.INVESTIGATING
        review_reason = review_reason or "Merchant could not be identified, so no dispute can be addressed"
        action = ActionProposal(type=ActionType.WARN_PERSON, service=ServiceDomain.PERSON, details={
            "message": f"We noticed a debit of R{signals['amount']:.2f} to {who} that we could not verify. Your family contact has been asked to check it."})
    elif risk >= CONTAIN_THRESHOLD:
        if threat in (ThreatDomain.TECH_SUPPORT_SCAM, ThreatDomain.IDENTITY_FARMING):
            severity = SeverityLevel.HIGH
        action = ActionProposal(type=ActionType.FLAG_SENDER, service=ServiceDomain.MAIL_FILTER, details={
            "target": signals["sender"] if shared_provider or not signals["sender_domain"] else signals["sender_domain"],
            "message": f"A message from {who} looks like a scam. We have blocked the sender. Please do not reply, pay, or call any number in it."})
    else:
        severity, target_state = SeverityLevel.LOW, IncidentState.INVESTIGATING
        action = ActionProposal(type=ActionType.WARN_PERSON, service=ServiceDomain.PERSON, details={
            "message": f"A message from {who} looks unusual. Please do not pay or share any details until it has been checked."})

    if "message" in action.details:
        action.details["message"] = _kind_wording(action.details["message"])
    if incident.status is IncidentState.RESOLVED:
        target_state = IncidentState.INVESTIGATING
    return Assessment(severity=severity, confidence=confidence, requested_state=target_state, proposed_action=action,
                      rationale=rationale, review_reason=review_reason, labels=labels)
