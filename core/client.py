"""Optional structured Gemini client. The engine remains usable offline."""
import os
from typing import TypeVar

from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

T = TypeVar("T", bound=BaseModel)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8), reraise=True)
def _generate(prompt: str, schema: type[T], api_key: str):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    try:
        return client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.1),
        )
    finally:
        client.close()


def call_agent_structured(prompt: str, schema: type[T]) -> T:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    response = _generate(prompt, schema, api_key)
    if response.parsed is None:
        raise ValueError("Gemini returned no structured response")
    return schema.model_validate(response.parsed)
