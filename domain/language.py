"""The one language job given to Gemini: wording a warning kindly. Python checks the text before using it.

Gemini does not classify, score, choose actions or change state here. The
function raises on failure and the caller falls back to the standard wording.
"""
from pathlib import Path

from pydantic import BaseModel

from core.client import call_agent_structured
from domain.extract import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


class PersonMessage(BaseModel):
    message: str


def write_person_message(facts: dict[str, str]) -> str:
    """Word a warning for the protected person from facts we chose. The raw message is never shown to the model."""
    prompt = (PROMPTS / "person_message.md").read_text(encoding="utf-8") + "\n\nFacts:\n" + "\n".join(f"- {name}: {value}" for name, value in facts.items())
    message = " ".join(call_agent_structured(prompt, PersonMessage).message.split())
    if not message or len(message) > 400 or any(pattern.search(message) for pattern in (URL_PATTERN, EMAIL_PATTERN, PHONE_PATTERN)):
        raise ValueError("generated message failed the safety check")
    return message
