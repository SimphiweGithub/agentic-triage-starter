"""Plain-language briefs for the caregiver, with a link that opens WhatsApp with the brief already typed."""
import os
from urllib.parse import quote

from domain.schemas import DecisionRecord, ReviewItem


def guardian_brief(review: ReviewItem, decision: DecisionRecord) -> dict[str, str]:
    """One pending review as a short message a caregiver can read on their phone."""
    details = review.proposed_action.details if review.proposed_action else {}
    question = details.get("ask") or review.reason
    why = decision.trace[1] if len(decision.trace) > 1 else ""
    text = f"Scam Stop: {question} Why we flagged it: {why} Open Scam Stop to approve or reject."
    if details.get("dispute_by"):
        text += f" A dispute must be lodged by {details['dispute_by']}."
    number = "".join(character for character in os.getenv("GUARDIAN_WHATSAPP", "") if character.isdigit())
    return {"review_id": review.review_id, "incident_id": review.incident_id, "text": text,
            "whatsapp_link": f"https://wa.me/{number}?text={quote(text)}"}
