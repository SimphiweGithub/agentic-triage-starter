"""Fast first look at a message: decide whether it deserves investigation.

Rules always run. A decision model (Jev) can be added on top: it answers the
same yes/no questions about wording the rules might miss. The model can add
suspicion; it can never remove what a rule found.
"""
from dataclasses import dataclass
import re
from typing import Any, Callable

from core.jev import system_one
from domain.enums import ThreatDomain
from domain.policy import MODEL_THREAT_CONFIDENCE, MODEL_YES

# key -> (reason shown in the trace, weight added to the score, pattern that triggers it)
# The last three rules were written from the development split of the UCI SMS Spam
# Collection and checked on a held-out fifth (see calibrate.py and RATIONALE.md).
TEXT_RULES: dict[str, tuple[str, float, re.Pattern]] = {
    "urgency": ("urgent or threatening wording", 0.25,
                re.compile(r"\b(urgent|immediately|final notice|last warning|suspended|within 24 hours|legal action|act now)\b", re.I)),
    "credentials": ("asks for credentials or remote access", 0.35,
                    re.compile(r"\b((confirm|verify|enter|send|share|provide) your (pin|password|card|details|account)|anydesk|teamviewer|remote access)\b", re.I)),
    "payment": ("asks for an unusual payment method", 0.35,
                re.compile(r"\b(gift card|voucher|bitcoin|crypto|e-?wallet)\b", re.I)),
    "subscription": ("subscription or renewal wording", 0.15,
                     re.compile(r"\b(subscription|auto[- ]?renew\w*|free trial|premium|membership|protection plan)\b", re.I)),
    "prize": ("says the reader has won or been selected", 0.3,
              re.compile(r"\b((you|u) have won|winner|prize|awarded|guaranteed|congratulations|been selected|reward)\b", re.I)),
    "claim": ("tells the reader to call or text a number to claim", 0.3,
              re.compile(r"\b(to claim|claim (your|ur|now|code)|call (now|free|0\d{9,})|(txt|text|send|sms) \w+ to \d{4,6})\b", re.I)),
    "premium": ("premium-rate number or paid-message terms", 0.3,
                re.compile(r"(\b\d{2,3}p\b|\bR ?\d+(\.\d{2})? ?(/|per ) ?(day|week|wk|msg|sms|min)|\bper (min|msg|sms|week|wk|text)\b|/min|/msg|/wk"
                           r"|\b(reply|txt|text|sms) stop\b|\bstop to\b|\bunsub(scribe)?\b|\bstd (txt|msg|rate)\b|\b09\d{8,9}\b|\b08[47]\d{7,9}\b)", re.I)),
    "impersonation": ("claims to be someone the reader knows, on a new number", 0.2,
                      re.compile(r"\b(new number|changed my number|lost my phone|phone (is|was) (broken|stolen)|this is my new)\b", re.I)),
    "money": ("asks the reader to send money", 0.3,
              re.compile(r"\b(send (me |us )?(some )?(money|cash|airtime|R ?\d+)|(deposit|transfer|pay) (me |us )?(the |a |some )?(money|fee|deposit|R ?\d+))\b", re.I)),
    "advance_fee": ("promises money or a parcel once a fee is paid", 0.3,
                    re.compile(r"\b(inheritance|dear beneficiary|unclaimed (funds?|package|parcel)|(release|processing|clearance|customs|admin) fee|lottery)\b", re.I)),
}
TECH_SUPPORT_PATTERN = re.compile(r"\b(tech(nical)? support|virus|infected|anydesk|teamviewer|remote access|protection plan)\b", re.I)

# The same judgements, asked of the decision model as yes/no questions, plus the threat type.
MODEL_QUESTIONS: dict[str, dict] = {
    "urgency": {"type": "noul", "instructions": "The message pressures the reader to act quickly or threatens a consequence if they do not."},
    "credentials": {"type": "noul", "instructions": "The message asks the reader to share a password, PIN, card or account details, or to give someone remote access to their device."},
    "payment": {"type": "noul", "instructions": "The message asks the reader to pay with gift cards, vouchers, cryptocurrency or another unusual method."},
    "subscription": {"type": "noul", "instructions": "The message tells the reader about a subscription, renewal, membership or recurring charge."},
    "prize": {"type": "noul", "instructions": "The message tells the reader they have won a prize, a reward or money, or have been specially selected."},
    "claim": {"type": "noul", "instructions": "The message tells the reader to call or text a number in order to claim or collect something."},
    "premium": {"type": "noul", "instructions": "The message involves a premium-rate number or a service that charges per message, per minute, per day or per week."},
    "impersonation": {"type": "noul", "instructions": "The sender claims to be a relative or friend of the reader writing from a new or different number."},
    "money": {"type": "noul", "instructions": "The message asks the reader to send, transfer or deposit money."},
    "advance_fee": {"type": "noul", "instructions": "The message promises money, an inheritance or a parcel once the reader pays a fee."},
    "threat": {"type": "choice", "instructions": "Which kind of message is this?", "criteria": {
        ThreatDomain.BENIGN.value: "An ordinary message with no sign of a scam",
        ThreatDomain.GREY_MARKET_SUBSCRIPTION.value: "A subscription, premium-rate service or recurring charge the reader may not have knowingly agreed to",
        ThreatDomain.IDENTITY_FARMING.value: "An attempt to collect passwords, PINs, card details or identity documents",
        ThreatDomain.TECH_SUPPORT_SCAM.value: "Fake technical support, a fake virus warning, or a request for remote access",
        ThreatDomain.PRIZE_SCAM.value: "A fake prize, lottery win or reward the reader must act to claim",
        ThreatDomain.IMPERSONATION.value: "Someone pretending to be a relative or friend, usually asking for money",
        ThreatDomain.ADVANCE_FEE.value: "A promise of money, an inheritance or a parcel in return for an upfront fee",
        ThreatDomain.UNKNOWN.value: "Suspicious, but none of the above",
    }},
}


def ask_jev(text: str) -> dict[str, dict]:
    """The model scorer used when ENABLE_JEV=1. Only the masked message text is sent."""
    return system_one({"message": text}, MODEL_QUESTIONS)


@dataclass(frozen=True)
class GateVerdict:
    score: float
    reasons: list[str]        # findings that added to the score
    threat: ThreatDomain
    notes: tuple[str, ...] = ()  # remarks that did not affect the score


def gate(text: str, signals: dict[str, Any], ask_model: Callable[[str], dict[str, dict]] | None = None) -> GateVerdict:
    """Score a message from 0 to 1. `ask_model` is optional; without it, or if it fails, the rules stand alone."""
    score, reasons, hits, notes = 0.0, [], set(), []
    for key, (reason, weight, pattern) in TEXT_RULES.items():
        if pattern.search(text or ""):
            score += weight
            reasons.append(reason)
            hits.add(key)
    if signals["reply_to_domain"] and signals["reply_to_domain"] != signals["sender_domain"]:
        score += 0.2
        reasons.append("replies go to a different domain than the sender")
    if signals["auth_fail"]:
        score += 0.25
        reasons.append("sender failed the mail provider's authentication checks")
    if signals["link_mismatch"]:
        score += 0.3
        reasons.append("a link shows one address but leads to another")

    model_threat = None
    if ask_model is not None:
        try:
            answers = ask_model(text or "")
            for key, (reason, weight, _) in TEXT_RULES.items():
                probability = float(answers[key]["noul"])
                if key not in hits and probability >= MODEL_YES:
                    score += weight
                    reasons.append(f"{reason} (decision model, {probability:.2f})")
                    hits.add(key)
            if float(answers["threat"]["confidence"]) >= MODEL_THREAT_CONFIDENCE:
                model_threat = ThreatDomain(answers["threat"]["choice"])
        except Exception as error:  # the gate must work without the model
            notes.append(f"decision model unavailable ({type(error).__name__}); rules only")
    score = min(score, 1.0)

    if score == 0:
        threat = ThreatDomain.BENIGN
    elif model_threat not in (None, ThreatDomain.BENIGN):
        threat = model_threat
    elif TECH_SUPPORT_PATTERN.search(text or ""):
        threat = ThreatDomain.TECH_SUPPORT_SCAM
    elif "credentials" in hits:
        threat = ThreatDomain.IDENTITY_FARMING
    elif "impersonation" in hits:
        threat = ThreatDomain.IMPERSONATION
    elif "advance_fee" in hits:
        threat = ThreatDomain.ADVANCE_FEE
    elif "prize" in hits:
        threat = ThreatDomain.PRIZE_SCAM
    elif signals["kind"] == "debit" or hits & {"subscription", "premium"}:
        threat = ThreatDomain.GREY_MARKET_SUBSCRIPTION
    else:
        threat = ThreatDomain.UNKNOWN
    return GateVerdict(round(score, 2), reasons, threat, tuple(notes))
