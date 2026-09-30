"""The two language jobs given to Gemini. Both return text that Python checks before using it.

Gemini does not classify, score, choose actions or change state here. It
helps where rules are weak: reading a garbled merchant name, and wording a
warning kindly. Each function raises on failure and the caller falls back.
"""
from pathlib import Path

from pydantic import BaseModel, Field

from core.client import call_agent_structured
from domain.extract import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


class NameSuggestions(BaseModel):
    names: list[str] = Field(default_factory=list)


class PersonMessage(BaseModel):
    message: str


def suggest_merchant_names(descriptor: str) -> list[str]:
    """Bank statements shorten merchant names. Ask for up to three full company names the descriptor could stand for."""
    prompt = (PROMPTS / "merchant_names.md").read_text(encoding="utf-8") + f"\n\nDescriptor: {descriptor!r}"
    return [name.strip() for name in call_agent_structured(prompt, NameSuggestions).names if name.strip()][:3]


def write_person_message(facts: dict[str, str]) -> str:
    """Word a warning for the protected person from facts we chose. The raw message is never shown to the model."""
    prompt = (PROMPTS / "person_message.md").read_text(encoding="utf-8") + "\n\nFacts:\n" + "\n".join(f"- {name}: {value}" for name, value in facts.items())
    message = " ".join(call_agent_structured(prompt, PersonMessage).message.split())
    if not message or len(message) > 400 or any(pattern.search(message) for pattern in (URL_PATTERN, EMAIL_PATTERN, PHONE_PATTERN)):
        raise ValueError("generated message failed the safety check")
    return message
