"""Ordered local replay. Adapt domain.logic.parse_record for challenge fields."""
import argparse
import csv
import json
from pathlib import Path

from core.runtime import TriageRuntime
from domain.logic import parse_record


def read_records(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        if path.suffix.lower() == ".csv":
            yield from csv.DictReader(source)
        elif path.suffix.lower() == ".jsonl":
            for line in source:
                if line.strip():
                    yield json.loads(line)
        else:
            raise ValueError("Input must be CSV or JSONL")


def run(input_path: Path, output_path: Path) -> int:
    runtime = TriageRuntime()
    count = 0
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for record in read_records(input_path):
            decision = runtime.process(parse_record(record))
            output.write(decision.model_dump_json() + "\n")
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("decisions.jsonl"))
    args = parser.parse_args()
    print(f"Wrote {run(args.input, args.output)} decisions to {args.output}")


if __name__ == "__main__":
    main()
