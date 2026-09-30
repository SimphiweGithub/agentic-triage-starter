"""Local scoring harness for decision JSONL.

Without --truth it runs mechanical checks only. With --truth it also scores
clustering, labels, actions and review against a labelled file. Truth rows are
JSONL keyed by report_id; every other field is optional and only the fields
present are scored:

    {"report_id": "R1", "event_id": "E1", "relationship": "NEW", "severity": "LOW",
     "status": "TRIAGED", "human_review": false, "actions": [{"type": "X", "service": "Y"}]}

`actions` lists the acceptable actions; [] means no action is expected.
Adjust TRUTH_TO_DECISION when the judges' output contract renames fields.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from core.ingest import read_records
from domain.enums import IncidentState, Relationship, SeverityLevel
from domain.logic import withhold
from domain.policy import FORBIDDEN_ACTIONS

# truth field -> decision field
TRUTH_TO_DECISION = {"relationship": "relationship", "severity": "severity", "status": "status",
                     "human_review": "requires_human_approval"}
SEVERITY_ORDER = [level.value for level in SeverityLevel]


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 2) if whole else 100.0


def _pairs(counter: Counter) -> int:
    return sum(size * (size - 1) // 2 for size in counter.values())


def clustering(truth_events: dict[str, str], predicted: dict[str, str]) -> dict[str, float | int]:
    """Pairwise precision, recall and F1. Incident IDs need not match the truth IDs."""
    ids = [report_id for report_id in truth_events if report_id in predicted]
    tp = _pairs(Counter((truth_events[i], predicted[i]) for i in ids))
    fp = _pairs(Counter(predicted[i] for i in ids)) - tp
    fn = _pairs(Counter(truth_events[i] for i in ids)) - tp
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def _action_key(action: dict | None) -> tuple | None:
    return (action.get("type"), action.get("service")) if isinstance(action, dict) else None


def evaluate(input_rows: list[dict], decisions: list[dict], truth: list[dict] | None = None) -> dict:
    input_rows = [row for row in input_rows if withhold(row) is None]  # withheld rows are meant to produce no decision
    input_ids = [str(row.get("report_id", "")) for row in input_rows]
    output_ids = [str(row.get("report_id", "")) for row in decisions]
    # A row with no usable report_id is covered by the runner's synthetic ROW-nnnnn decision.
    covered = sum(a == b or (a in ("", "None") and b.startswith("ROW-")) for a, b in zip(input_ids, output_ids))
    valid_states = sum(row.get("status") in IncidentState._value2member_map_ for row in decisions)
    duplicates = [row for row in decisions if row.get("relationship") == Relationship.DUPLICATE.value]
    duplicate_safety = sum(row.get("proposed_action") is None for row in duplicates)
    forbidden = {action.value for action in FORBIDDEN_ACTIONS}
    forbidden_total = [row for row in decisions if isinstance(row.get("proposed_action"), dict)
                       and row["proposed_action"].get("type") in forbidden]
    forbidden_safe = sum(row.get("requires_human_approval") is True for row in forbidden_total)
    result = {
        "input_count": len(input_rows),
        "output_count": len(decisions),
        "coverage_percent": _percent(covered, len(input_rows)),
        "state_validity_percent": _percent(valid_states, len(decisions)),
        "duplicate_suppression_percent": _percent(duplicate_safety, len(duplicates)),
        "forbidden_action_review_percent": _percent(forbidden_safe, len(forbidden_total)),
    }
    if truth is None:
        return result

    by_id = {str(row.get("report_id")): row for row in decisions}
    issues: dict[str, list[str]] = {}
    hits, totals = Counter(), Counter()

    def check(name: str, report_id: str, correct: bool, message: str) -> None:
        totals[name] += 1
        hits[name] += correct
        if not correct:
            issues.setdefault(report_id, []).append(message)

    for row in truth:
        report_id = str(row.get("report_id"))
        decision = by_id.get(report_id)
        if decision is None:
            issues.setdefault(report_id, []).append("missing decision")
            continue
        for truth_field, decision_field in TRUTH_TO_DECISION.items():
            if truth_field in row:
                got, want = decision.get(decision_field), row[truth_field]
                check(truth_field, report_id, got == want, f"{truth_field}: got {got}, expected {want}")
        if "severity" in row and row["severity"] in SEVERITY_ORDER and decision.get("severity") in SEVERITY_ORDER:
            gap = abs(SEVERITY_ORDER.index(row["severity"]) - SEVERITY_ORDER.index(decision["severity"]))
            totals["severity_within_one"] += 1
            hits["severity_within_one"] += gap <= 1
        if "actions" in row:
            got = _action_key(decision.get("proposed_action"))
            acceptable = {_action_key(action) for action in row["actions"]}
            correct = got is None if not acceptable else got in acceptable
            check("action", report_id, correct, f"action: got {got}, expected one of {sorted(acceptable, key=str) or 'none'}")

    events = {str(row["report_id"]): str(row["event_id"]) for row in truth if "event_id" in row}
    if events:
        result["clustering"] = clustering(events, {i: str(d.get("incident_id")) for i, d in by_id.items()})
        result["truth_events"] = len(set(events.values()))
        result["predicted_incidents"] = len({str(by_id[i].get("incident_id")) for i in events if i in by_id})
    wanted = [str(r["report_id"]) for r in truth if r.get("human_review") is True and str(r.get("report_id")) in by_id]
    if "human_review" in totals:
        result["review_recall_percent"] = _percent(sum(by_id[i].get("requires_human_approval") is True for i in wanted), len(wanted))
    for name in totals:
        result[f"{name}_accuracy_percent"] = _percent(hits[name], totals[name])
    result["issue_counts"] = dict(Counter(message.split(":")[0] for messages in issues.values() for message in messages))
    result["report_issues"] = [{"report_id": report_id, "issues": messages} for report_id, messages in issues.items()]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Input CSV or JSONL with report_id fields")
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--truth", type=Path, help="Labelled JSONL keyed by report_id")
    parser.add_argument("--issues", action="store_true", help="Print the per-report issue list")
    args = parser.parse_args()
    truth = load_jsonl(args.truth) if args.truth else None
    result = evaluate(list(read_records(args.input)), load_jsonl(args.decisions), truth)
    if not args.issues:
        result.pop("report_issues", None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
