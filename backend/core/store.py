"""Keep the engine's memory on disk, so a restart does not wipe every incident.

Each runtime's whole state is written to one JSON file after every change and
read back when the server starts. The shared runtime uses KINGUARD_STATE_FILE
(default data/state.json); each person's runtime uses people/<person id>.json
beside it. An empty KINGUARD_STATE_FILE keeps everything in memory only (the
tests do this).
"""
import json
import os
from pathlib import Path

from domain.schemas import DecisionRecord, IncidentRecord, RawInputReport, ReviewItem
from domain.tools import restore_world, world_state

DEFAULT_FILE = Path(__file__).resolve().parents[1] / "data" / "state.json"


def state_file(person_id: str | None = None) -> Path | None:
    """Where a runtime is saved: the shared file, or the person's own file next to it. None means do not save."""
    value = os.getenv("KINGUARD_STATE_FILE")
    shared = DEFAULT_FILE if value is None else Path(value) if value.strip() else None
    if shared is None or person_id is None:
        return shared
    return shared.parent / "people" / f"{person_id}.json"


def save(runtime) -> None:
    """Write the runtime to its file. Call it with the runtime's own world active, so `world_state` is that person's."""
    path = runtime.state_path
    if path is None:
        return
    data = {
        "reports": [item.model_dump(mode="json") for item in runtime.reports.values()],
        "incidents": [item.model_dump(mode="json") for item in runtime.incidents.values()],
        "decisions": [item.model_dump(mode="json") for item in runtime.decisions.values()],
        "reviews": [item.model_dump(mode="json") for item in runtime.reviews.values()],
        "report_number": runtime.report_number,
        "world": world_state(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)  # the old file is only replaced once the new one is complete


def load(runtime) -> bool:
    """Fill the runtime from its file, with its own world active. Returns False if there is nothing to load."""
    path = runtime.state_path
    if path is None or not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    runtime.reports = {item["report_id"]: RawInputReport.model_validate(item) for item in data["reports"]}
    runtime.incidents = {item["incident_id"]: IncidentRecord.model_validate(item) for item in data["incidents"]}
    runtime.decisions = {item["report_id"]: DecisionRecord.model_validate(item) for item in data["decisions"]}
    runtime.reviews = {item["review_id"]: ReviewItem.model_validate(item) for item in data["reviews"]}
    runtime.report_number = data.get("report_number", len(data["reports"]))  # files saved before the counter was kept
    restore_world(data["world"])
    return True
