"""Ordered, tolerant input reading shared by the CLI runner and the replay API."""
import csv
import io
import json
from pathlib import Path
from typing import Any, Iterator

from domain.logic import parse_record, withhold
from domain.schemas import RawInputReport


def read_text_records(text: str, suffix: str) -> Iterator[dict[str, Any]]:
    """Yield rows in file order. Unreadable JSONL lines are yielded as error rows, not dropped."""
    suffix = suffix.lower()
    if suffix == ".csv":
        yield from csv.DictReader(io.StringIO(text, newline=""))
    elif suffix == ".jsonl":
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("line is not a JSON object")
            except ValueError as error:
                row = {"payload": line, "_parse_error": str(error)}
            yield row
    else:
        raise ValueError("Input must be CSV or JSONL")


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    yield from read_text_records(path.read_text(encoding="utf-8-sig"), path.suffix)


def kept(rows: Iterator[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Drop rows the domain says must never be stored, such as one-time codes."""
    return (row for row in rows if withhold(row) is None)


def safe_parse(row: dict[str, Any], index: int) -> tuple[RawInputReport, str | None]:
    """Never raises. A row that cannot be parsed still becomes a report, with the error returned."""
    error = row.get("_parse_error")
    if error is None:
        try:
            return parse_record(row), None
        except Exception as failure:
            error = f"{type(failure).__name__}: {failure}".splitlines()[0]
    report_id = str(row.get("report_id") or "").strip() or f"ROW-{index:05d}"
    payload = row.get("payload")
    return RawInputReport(report_id=report_id, payload=payload if isinstance(payload, str) else "",
                          metadata={"raw_row": {str(key): str(value) for key, value in row.items()}}), str(error)
