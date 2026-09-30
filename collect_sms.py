"""Turn an "SMS Backup & Restore" export into a small file of messages ready to be labelled.

Everything runs on this machine. The script keeps only received texts from
senders who are not saved contacts, drops one-time codes, masks account
numbers, and takes a limited sample so the file is short enough to label by
hand. Output lines are `?<TAB>text<TAB>sender`; a person then replaces each
`?` with `scam` or `benign`.
"""
import argparse
from collections import defaultdict
from pathlib import Path
import random
import re
import xml.etree.ElementTree as ET

from domain.extract import is_one_time_code, redact

RECEIVED = "1"                      # the export marks received texts with type 1 and sent texts with type 2
NOT_A_CONTACT = {"", "(unknown)", "null"}
MONTHS = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b")


def collect(export: Path, per_sender: int, limit: int, seed: int = 1) -> list[tuple[str, str]]:
    """Returns (text, sender) pairs: received, not from a saved contact, no one-time codes, numbers masked."""
    by_sender: dict[str, list[str]] = defaultdict(list)
    seen = set()
    for sms in ET.parse(export).getroot().iter("sms"):
        text = " ".join((sms.get("body") or "").split())
        if sms.get("type") != RECEIVED or (sms.get("contact_name") or "").strip().lower() not in NOT_A_CONTACT:
            continue
        if not text or is_one_time_code(text):
            continue
        text = redact(text)
        shape = MONTHS.sub("month", re.sub(r"\d+", "0", text.lower()))  # the same notice with other amounts or dates counts once
        if shape in seen:
            continue
        seen.add(shape)
        by_sender[sms.get("address") or "unknown"].append(text)
    chooser = random.Random(seed)
    sample = [(text, sender) for sender, texts in by_sender.items() for text in chooser.sample(texts, min(per_sender, len(texts)))]
    chooser.shuffle(sample)
    return sample[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path, help="The .xml file made by SMS Backup & Restore")
    parser.add_argument("--output", type=Path, default=Path("data/sa_messages.tsv"))
    parser.add_argument("--per-sender", type=int, default=8, help="Most messages to keep from any one sender")
    parser.add_argument("--limit", type=int, default=150, help="Most messages to keep in total")
    args = parser.parse_args()
    sample = collect(args.export, args.per_sender, args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"?\t{text}\t{sender}\n" for text, sender in sample), encoding="utf-8", newline="\n")
    print(f"Wrote {len(sample)} messages to {args.output}. Replace each ? with scam or benign, then run calibrate.py on it.")


if __name__ == "__main__":
    main()
