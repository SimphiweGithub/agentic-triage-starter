"""Gather evidence about a suspicious message by calling the read-only tools."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain.policy import JUMP_RATIO, PROTECTED_DOMAINS, YOUNG_DAYS
from domain.tools import domain_age, mandate_history, merchant_registry


@dataclass(frozen=True)
class Finding:
    source: str          # which tool produced it
    weight: float        # how much it adds to the risk score; 0 means no added risk
    note: str            # what the tool found, in words
    reassuring: bool = False  # true when the finding points towards a legitimate sender


def investigate(signals: dict[str, Any], when: datetime) -> tuple[list[Finding], dict[str, Any] | None]:
    """Returns the findings and, when the merchant was identified, its registry record."""
    findings: list[Finding] = []
    company = None

    for domain in signals["domains"]:
        if domain in PROTECTED_DOMAINS:
            continue
        result = domain_age(domain, when)
        if not result.ok:
            findings.append(Finding("domain_age", 0.0, result.detail))
        elif result.data["age_days"] < YOUNG_DAYS:
            findings.append(Finding("domain_age", 0.3, result.detail))
        else:
            findings.append(Finding("domain_age", 0.0, result.detail, reassuring=True))

    if signals["merchant"]:
        result = merchant_registry(signals["merchant"], when=when)
        if not result.ok and signals["reference"]:
            # Self-correction: the name alone was ambiguous or unknown, so look again using the payment reference.
            findings.append(Finding("merchant_registry", 0.0, f"{result.detail}; retrying with reference {signals['reference']}"))
            result = merchant_registry(signals["merchant"], signals["reference"], when)
        if not result.ok:
            findings.append(Finding("merchant_registry", 0.1, result.detail))
        elif result.data["age_days"] < YOUNG_DAYS:
            company = result.data
            findings.append(Finding("merchant_registry", 0.25, result.detail))
        else:
            company = result.data
            findings.append(Finding("merchant_registry", 0.0, result.detail, reassuring=True))

    if signals["kind"] == "debit":
        result = mandate_history(signals["merchant"], signals["amount"])
        if result.data["first_time"]:
            findings.append(Finding("mandate_history", 0.2, result.detail))
        elif result.data["ratio"] and result.data["ratio"] >= JUMP_RATIO:
            findings.append(Finding("mandate_history", 0.35, result.detail))
        else:
            findings.append(Finding("mandate_history", 0.0, result.detail, reassuring=True))

    return findings, company
