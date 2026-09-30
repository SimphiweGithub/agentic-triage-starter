"""Turn raw message text into the facts the agent reasons about. Runs before anything is stored."""
import re
from typing import Any

OTP_PATTERN = re.compile(r"\b(otp|one[- ]time (?:pin|password|passcode)|verification code|security code|login code)\b", re.I)
# A message that hands over a secret: "your password is ...", "recovery code", "login details". A scam that asks
# the reader to "confirm your password" does not match, so it is still analysed.
SECRET_PATTERN = re.compile(r"\b((password|passcode|pin|username|user name|code)\s*(is|:|=)|(recovery|reset|backup|access|activation) codes?"
                            r"|(code|pin)\s*#?\s*\d{4,8}|temporary password|login details|log ?in details)\b", re.I)
ACCOUNT_PATTERN = re.compile(r"(?<![+\d])(?!0\d{9}\b)\d{9,19}\b")
# Numbers written in groups of four, such as card numbers and prepaid electricity tokens: "4111 1111 1111 1111".
GROUPED_PATTERN = re.compile(r"(?<!\d)(?:\d{4}[ -]){3,}\d{1,4}(?!\d)")
AMOUNT_PATTERN = re.compile(r"\bR\s?(\d{1,3}(?:[ ,]\d{3})+|\d+)(\.\d{2})?")
URL_PATTERN = re.compile(r"(?:https?://|www\.)([a-z0-9.-]+\.[a-z]{2,})", re.I)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@([a-z0-9.-]+\.[a-z]{2,})", re.I)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+27|0)[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
REFERENCE_PATTERN = re.compile(r"\bref(?:erence)?[\s:#.]*([A-Z]{1,4}\d{3,})", re.I)
MANDATE_PATTERN = re.compile(r"\b(mandate (registered|request\w*)|new mandate|debit order (approval|request)|approve (this|the|a) (debit|mandate))\b", re.I)
DEBIT_PATTERN = re.compile(r"\b(debit order|debit|deducted|charged|recurring payment|subscription payment)\b", re.I)
MERCHANT_PATTERN = re.compile(r"\b(?:to|from|by|at)\s+([A-Z][A-Za-z0-9&' -]{2,40}?)(?=\s+(?:ref|reference|on|for|acc|account)\b|[.,;:]|$)")


def is_one_time_code(text: str) -> bool:
    """Messages carrying login or payment codes, passwords or recovery codes are never stored or sent to a model."""
    return bool(OTP_PATTERN.search(text or "") or SECRET_PATTERN.search(text or ""))


def redact(text: str) -> str:
    """Mask account numbers, card numbers and tokens. Phone numbers are kept as evidence."""
    return ACCOUNT_PATTERN.sub("[number withheld]", GROUPED_PATTERN.sub("[number withheld]", text or ""))


def domain_of(value: str) -> str:
    """The domain in an address or link, lower case and without a leading www."""
    match = EMAIL_PATTERN.search(value or "") or URL_PATTERN.search(value or "")
    return match.group(1).lower().removeprefix("www.") if match else ""


def normalise_name(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (name or "").lower()))


def extract_signals(text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    text = text or ""
    amount_match = AMOUNT_PATTERN.search(text)
    amount = float(amount_match.group(1).replace(" ", "").replace(",", "") + (amount_match.group(2) or "")) if amount_match else None
    is_mandate = bool(MANDATE_PATTERN.search(text))  # a request to set up a debit, not a debit that has run
    is_debit = bool(DEBIT_PATTERN.search(text)) and amount is not None and not is_mandate
    merchant_match = MERCHANT_PATTERN.search(text) if is_debit or is_mandate else None
    merchant = merchant_match.group(1) if merchant_match else str(metadata.get("sender_name") or "")
    reference = REFERENCE_PATTERN.search(text)
    sender = str(metadata.get("sender") or "").lower()
    links = [(str(label), str(target)) for label, target in metadata.get("links") or []]
    domains = [domain_of(sender), domain_of(str(metadata.get("reply_to") or ""))]
    domains += [found.lower().removeprefix("www.") for found in URL_PATTERN.findall(text)]
    domains += [domain_of(target) for _, target in links]
    # A link label that shows a different address from its target is bait, not one of the sender's domains.
    bait = {domain_of(label) for label, target in links if domain_of(label) != domain_of(target)}
    return {
        "kind": "mandate" if is_mandate else "debit" if is_debit else "message",
        "merchant": normalise_name(merchant),
        "amount": amount,
        "reference": reference.group(1).upper() if reference else "",
        "sender": sender,
        "sender_domain": domain_of(sender),
        "reply_to_domain": domain_of(str(metadata.get("reply_to") or "")),
        "domains": sorted({domain for domain in domains if domain} - bait),
        "phones": sorted({re.sub(r"\D", "", phone) for phone in PHONE_PATTERN.findall(text)}),
        "auth_fail": bool(metadata.get("auth_fail")),
        "link_mismatch": any(domain_of(label) and domain_of(label) != domain_of(target) for label, target in links),
    }
