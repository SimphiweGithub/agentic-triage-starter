"""Scam Stop decisions: how a message is read, linked to an incident, and assessed."""
from datetime import datetime, timedelta, timezone
import os
from typing import Any

from domain.enums import ActionOutcome, ActionType, IncidentState, ServiceDomain, SeverityLevel, ThreatDomain
from domain.extract import extract_signals, is_one_time_code, redact
from domain.gate import ask_jev, gate
from domain.investigate import investigate
from domain.language import write_person_message
from domain.policy import (CONTAIN_THRESHOLD, COOLING_OFF_SECONDS, DISPUTE_WINDOW_DAYS, GATE_THRESHOLD, HIGH_AMOUNT,
                           PROTECTED_DOMAINS, REVIEW_HOLD_SEVERITIES, YOUNG_DAYS)
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


def review_audience() -> str:
    """Who a review is addressed to: the caregiver, or the person themselves when no guardian is enrolled."""
    return "CAREGIVER" if WORLD.guardian else "PERSON"


def _withdrawal(incident: IncidentRecord) -> Assessment:
    """The person says the charge or sender is legitimate: undo our actions, unless the evidence was strong."""
    strong = incident.severity in REVIEW_HOLD_SEVERITIES
    action = ActionProposal(type=ActionType.WITHDRAW, service=ServiceDomain.BANK,
                            details={"merchant": incident.labels.get("merchant", "")})
    if strong and WORLD.guardian:
        return Assessment(severity=incident.severity, confidence=0.5, requested_state=incident.status, proposed_action=action,
                          rationale="The person says this is legitimate, but the evidence against it was strong.",
                          review_reason="Person confirmed a high-risk sender as legitimate; check for coercion")
    if strong:  # nobody else to ask, so slow the decision down instead
        return Assessment(severity=incident.severity, confidence=0.5, requested_state=incident.status, proposed_action=action,
                          rationale="The person says this is legitimate, but the evidence against it was strong and no guardian is enrolled.",
                          review_reason="Person confirmed a high-risk sender as legitimate; cooling-off before it takes effect",
                          review_delay_seconds=COOLING_OFF_SECONDS)
    return Assessment(severity=SeverityLevel.LOW, confidence=0.95, requested_state=IncidentState.RESOLVED, proposed_action=action,
                      rationale="The person confirmed this is legitimate; withdrawing our actions and trusting the merchant.",
                      labels={"threat": ThreatDomain.BENIGN.value})


def learn_from_review(approved: bool, action: ActionProposal | None, report: RawInputReport) -> None:
    """When a human rejects a warning or a block, remember the sender, so the same doubt is not raised again."""
    if approved or action is None or action.type not in (ActionType.WARN_PERSON, ActionType.FLAG_SENDER):
        return
    sender = _signals(report)["sender"]
    if sender:
        WORLD.known_senders.add(sender)


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

    is_debit, is_mandate = signals["kind"] == "debit", signals["kind"] == "mandate"
    when = parse_timestamp(report.timestamp) or datetime.now(timezone.utc)
    verdict = gate(report.payload, signals, ask_jev if os.getenv("ENABLE_JEV") == "1" else None)
    findings, company = [], None
    if is_debit or is_mandate or verdict.score >= GATE_THRESHOLD:
        findings, company = investigate(signals, when)
    if is_debit:
        WORLD.debits.setdefault(signals["merchant"], []).append(signals["amount"])

    price_jump = any(finding.source == "mandate_history" and finding.weight > 0.3 for finding in findings)
    trusted = signals["merchant"] in WORLD.trusted and not price_jump
    risk = 0.0 if trusted else min(1.0, verdict.score + sum(finding.weight for finding in findings))
    known = signals["sender"] in WORLD.known_senders and risk < CONTAIN_THRESHOLD
    if known:  # a human said a doubtful warning from this sender was wrong; strong evidence still overrides that
        risk = 0.0
    evidence = verdict.reasons + [finding.note for finding in findings if finding.weight > 0]
    established = bool(company) and company["age_days"] >= YOUNG_DAYS
    if is_mandate and not trusted and not (established and verdict.score < GATE_THRESHOLD):
        # An approved mandate is hard to dispute later, so a request is advised against unless the company checks out.
        risk = max(risk, GATE_THRESHOLD)
        evidence.append("a new debit mandate is being requested by a company not verified as established")
    threat = verdict.threat
    if threat is ThreatDomain.BENIGN and risk >= GATE_THRESHOLD:  # the wording was clean but the tools found risk
        threat = ThreatDomain.GREY_MARKET_SUBSCRIPTION if is_debit or is_mandate else ThreatDomain.UNKNOWN
    labels = {"threat": threat.value, "merchant": signals["merchant"], "reg_no": (company or {}).get("reg_no", "")}
    labels = {name: value for name, value in labels.items() if value}
    stay = IncidentState.TRIAGED if incident.status is IncidentState.NEW else incident.status

    if risk < GATE_THRESHOLD:
        reason = ("merchant is trusted by the person" if trusted else "a person said this sender's messages are fine" if known
                  else "nothing suspicious found")
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

    amount_text = f"R{signals['amount']:.2f}" if signals["amount"] is not None else "an amount"
    if is_mandate:
        target_state = IncidentState.INVESTIGATING
        severity = SeverityLevel.HIGH if (signals["amount"] or 0) >= HIGH_AMOUNT else SeverityLevel.MEDIUM
        action = ActionProposal(type=ActionType.ADVISE_DECLINE, service=ServiceDomain.PERSON, details={
            "merchant": signals["merchant"],
            "message": f"A company called {who} is asking to take {amount_text} from your account. We could not confirm it is a trusted company. "
                       "We suggest you do not approve it. Once approved, it is hard to reverse."})
    elif is_debit and disputed:
        severity = SeverityLevel.HIGH
        rationale = "A debit arrived after the dispute was lodged, so the dispute did not stop this operator. " + rationale
        action = ActionProposal(type=ActionType.BLOCK_OPERATOR, service=ServiceDomain.BANK, details={
            "merchant": signals["merchant"], "operator": signals.get("operator", ""),
            "ask": f"{who} has taken money again after we disputed it. Shall we ask your bank to refuse every debit from this operator?"})
    elif is_debit and company:
        severity = SeverityLevel.HIGH if signals["amount"] >= HIGH_AMOUNT else SeverityLevel.MEDIUM
        action = ActionProposal(type=ActionType.DRAFT_DISPUTE, service=ServiceDomain.BANK, details={
            "merchant": signals["merchant"], "company": company["name"], "reg_no": company["reg_no"],
            "amount": signals["amount"], "reference": signals["reference"],
            "dispute_by": (when + timedelta(days=DISPUTE_WINDOW_DAYS)).date().isoformat(),
            "ask": f"{amount_text} was taken by {company['name']}, which we do not think you agreed to. Shall we prepare a dispute for your bank?"})
    elif is_debit:
        target_state = IncidentState.INVESTIGATING
        review_reason = review_reason or "Merchant could not be identified, so no dispute can be addressed"
        action = ActionProposal(type=ActionType.WARN_PERSON, service=ServiceDomain.PERSON, details={
            "message": f"We noticed a debit of {amount_text} to {who} that we could not verify. Please check it before paying anything more.",
            "ask": f"Scam Stop could not verify a debit of {amount_text} to {who}. Send a warning about it?"})
    elif risk >= CONTAIN_THRESHOLD:
        if threat in (ThreatDomain.TECH_SUPPORT_SCAM, ThreatDomain.IDENTITY_FARMING):
            severity = SeverityLevel.HIGH
        action = ActionProposal(type=ActionType.FLAG_SENDER, service=ServiceDomain.MAIL_FILTER, details={
            "target": signals["sender"] if shared_provider or not signals["sender_domain"] else signals["sender_domain"],
            "message": f"A message from {who} looks like a scam. We have blocked the sender. Please do not reply, pay, or call any number in it.",
            "ask": f"A message from {who} looks like a scam. Block the sender and send a warning?"})
    else:
        severity, target_state = SeverityLevel.LOW, IncidentState.INVESTIGATING
        action = ActionProposal(type=ActionType.WARN_PERSON, service=ServiceDomain.PERSON, details={
            "message": f"A message from {who} looks unusual. Please do not pay or share any details until it has been checked.",
            "ask": f"Scam Stop is not sure about a message from {who}. Send a warning about it? Say no if it is expected."})

    if "message" in action.details:
        action.details["message"] = _kind_wording(action.details["message"])
    if incident.status is IncidentState.RESOLVED:
        target_state = IncidentState.INVESTIGATING
    return Assessment(severity=severity, confidence=confidence, requested_state=target_state, proposed_action=action,
                      rationale=rationale, review_reason=review_reason, labels=labels)
