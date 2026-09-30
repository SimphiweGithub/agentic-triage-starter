"""Ordered local replay of a CSV or JSONL file of messages."""
import argparse
from pathlib import Path

from core.ingest import kept, read_records, safe_parse
from core.runtime import TriageRuntime


def run(input_path: Path, output_path: Path) -> int:
    """Writes one decision per kept input row, in file order. A bad row becomes a human-review decision."""
    runtime = TriageRuntime()
    count = 0
    with output_path.open("w", encoding="utf-8", newline="\n") as output:
        for index, record in enumerate(kept(read_records(input_path)), start=1):
            report, error = safe_parse(record, index)
            decision = runtime.process_safely(report, error)
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
