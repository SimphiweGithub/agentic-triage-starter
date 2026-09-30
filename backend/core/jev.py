"""Minimal client for TypeSafe's Jev decision model. It answers typed questions about a state; it writes no text."""
import json
import os
from typing import Any
import urllib.request

API_URL = "https://api.typesafe.ai/v1/systemone"


def system_one(state: Any, questions: dict[str, dict]) -> dict[str, dict]:
    """Send one state and a set of typed questions; return the answers keyed by question id. Raises on any failure."""
    api_key = os.getenv("TYPESAFE_API_KEY")
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not configured")
    body = json.dumps({"state": state, "model": os.getenv("TYPESAFE_MODEL", "jev-latest"), "questions": questions})
    request = urllib.request.Request(API_URL, data=body.encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)["answers"]
