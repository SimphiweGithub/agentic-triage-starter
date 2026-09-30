"""Keep the engine's memory on disk, so a restart does not wipe every incident.

The whole state is written to one JSON file after every change and read back
when the server starts. Set KINGUARD_STATE_FILE to choose the file, or to an
empty value to keep everything in memory only (the tests do this).
"""
import json
import os
from pathlib import Path

from domain.schemas import DecisionRecord, IncidentRecord, RawInputReport, ReviewItem
from domain.tools import restore_world, world_state

DEFAULT_FILE = Path(__file__).resolve().parents[1] / "data" / "state.json"


def state_file() -> Path | None:
    value = os.getenv("KINGUARD_STATE_FILE")
    if value is None:
        return DEFAULT_FILE
    return Path(value) if value.strip() else None


def save(runtime) -> None:
    path = state_file()
    if path is None:
        return
    data = {
        "reports": [item.model_dump(mode="json") for item in runtime.reports.values()],
        "incidents": [item.model_dump(mode="json") for item in runtime.incidents.values()],
        "decisions": [item.model_dump(mode="json") for item in runtime.decisions.values()],
        "reviews": [item.model_dump(mode="json") for item in runtime.reviews.values()],
        "world": world_state(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)  # the old file is only replaced once the new one is complete


def load(runtime) -> bool:
    """Fill the runtime from the file. Returns False if there is nothing to load."""
    path = state_file()
    if path is None or not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    runtime.reports = {item["report_id"]: RawInputReport.model_validate(item) for item in data["reports"]}
    runtime.incidents = {item["incident_id"]: IncidentRecord.model_validate(item) for item in data["incidents"]}
    runtime.decisions = {item["report_id"]: DecisionRecord.model_validate(item) for item in data["decisions"]}
    runtime.reviews = {item["review_id"]: ReviewItem.model_validate(item) for item in data["reviews"]}
    restore_world(data["world"])
    return True
