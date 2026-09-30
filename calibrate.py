"""Measure the gate on labelled messages, so thresholds are chosen from data instead of by feel.

Input is either JSONL rows with the usual message fields plus "label"
("scam" or "benign"), or a tab-separated file of `label<TAB>text` lines where
the label is scam/spam or benign/ham. The labels must come from someone other
than the person who wrote the rules, or the result only proves the rules agree
with themselves.
"""
import argparse
import json
import os
from pathlib import Path

from domain.extract import extract_signals, redact
from domain.gate import ask_jev, gate

SCAM_LABELS = {"scam", "spam"}
BENIGN_LABELS = {"benign", "ham"}


def load_labelled(path: Path) -> list[tuple[str, dict, bool]]:
    """Returns (text, metadata, is_scam) for every line. An unlabelled line stops the run instead of counting as benign."""
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        if path.suffix.lower() == ".jsonl":
            row = json.loads(line)
            label, text, metadata = str(row.get("label", "")), str(row.get("payload", "")), row.get("metadata") or {}
        else:
            cells = line.split("\t") + [""]  # label, text, and optionally the sender, which is ignored here
            label, text, metadata = cells[0], cells[1], {}
        label = label.strip().lower()
        if label not in SCAM_LABELS | BENIGN_LABELS:
            raise ValueError(f"line {number}: label {label!r} is not scam or benign. Label every line before measuring.")
        rows.append((text, metadata, label in SCAM_LABELS))
    return rows


def sweep(rows: list[tuple[str, dict, bool]], ask_model=None) -> list[dict]:
    """Score every message once, then count right and wrong calls at each threshold from 0.05 to 0.95."""
    scored = [(gate(redact(text), extract_signals(redact(text), metadata), ask_model).score, is_scam) for text, metadata, is_scam in rows]
    table = []
    for step in range(1, 20):
        threshold = step / 20
        tp = sum(score >= threshold and is_scam for score, is_scam in scored)
        fp = sum(score >= threshold and not is_scam for score, is_scam in scored)
        fn = sum(score < threshold and is_scam for score, is_scam in scored)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        table.append({"threshold": threshold, "caught": tp, "false_alarms": fp, "missed": fn,
                      "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)})
    return table


def split(rows: list, part: str) -> list:
    """Every fifth message is held out. Rules are written looking only at "dev" and judged on "holdout"."""
    if part == "holdout":
        return [row for index, row in enumerate(rows) if index % 5 == 0]
    if part == "dev":
        return [row for index, row in enumerate(rows) if index % 5]
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labelled", type=Path)
    parser.add_argument("--part", choices=("all", "dev", "holdout"), default="all")
    args = parser.parse_args()
    rows = split(load_labelled(args.labelled), args.part)
    table = sweep(rows, ask_jev if os.getenv("ENABLE_JEV") == "1" else None)
    print(f"{len(rows)} messages, {sum(is_scam for _, _, is_scam in rows)} labelled scam")
    print("threshold  caught  false_alarms  missed  precision  recall  f1")
    for line in table:
        print(f"{line['threshold']:9.2f}  {line['caught']:6d}  {line['false_alarms']:12d}  {line['missed']:6d}  "
              f"{line['precision']:9.3f}  {line['recall']:6.3f}  {line['f1']:.3f}")
    best = max(table, key=lambda line: line["f1"])
    print(f"Best F1 {best['f1']} at threshold {best['threshold']:.2f}. Set GATE_THRESHOLD in domain/policy.py from this table.")


if __name__ == "__main__":
    main()
