"""Mechanical checks for any future challenge data and decision JSONL."""
import argparse
import json
from pathlib import Path

from domain.enums import IncidentState, Relationship
from domain.policy import FORBIDDEN_ACTIONS


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


def evaluate(input_rows: list[dict], decisions: list[dict]) -> dict[str, float | int]:
    input_ids = [str(row.get("report_id", "")) for row in input_rows]
    output_ids = [str(row.get("report_id", "")) for row in decisions]
    covered = sum(a == b for a, b in zip(input_ids, output_ids))
    valid_states = sum(row.get("status") in IncidentState._value2member_map_ for row in decisions)
    duplicates = [row for row in decisions if row.get("relationship") == Relationship.DUPLICATE.value]
    duplicate_safety = sum(row.get("proposed_action") is None for row in duplicates)
    forbidden = {action.value for action in FORBIDDEN_ACTIONS}
    forbidden_total = [row for row in decisions if isinstance(row.get("proposed_action"), dict)
                       and row["proposed_action"].get("type") in forbidden]
    forbidden_safe = sum(row.get("requires_human_approval") is True for row in forbidden_total)
    return {
        "input_count": len(input_rows),
        "output_count": len(decisions),
        "coverage_percent": round(100 * covered / len(input_rows), 2) if input_rows else 100.0,
        "state_validity_percent": round(100 * valid_states / len(decisions), 2) if decisions else 100.0,
        "duplicate_suppression_percent": round(100 * duplicate_safety / len(duplicates), 2) if duplicates else 100.0,
        "forbidden_action_review_percent": round(100 * forbidden_safe / len(forbidden_total), 2) if forbidden_total else 100.0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input JSONL with report_id fields")
    parser.add_argument("decisions", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(load_jsonl(args.input), load_jsonl(args.decisions)), indent=2))


if __name__ == "__main__":
    main()
