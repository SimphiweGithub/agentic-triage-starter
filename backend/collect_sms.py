"""Turn an "SMS Backup & Restore" export into a small file of messages ready to be labelled.

Everything runs on this machine. The script keeps only received texts from
business senders (names, short codes, bulk numbers), drops one-time codes, masks account
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

from domain.extract import AMOUNT_PATTERN, EMAIL_PATTERN, PHONE_PATTERN, is_one_time_code, redact

RECEIVED = "1"                      # the export marks received texts with type 1 and sent texts with type 2
NOT_A_CONTACT = {"", "(unknown)", "null"}
MONTHS = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b")
TOKEN = re.compile(r"[A-Za-z0-9#/-]+")  # a run of letters, digits and joiners: an order number, a student number


def looks_personal(sender: str) -> bool:
    """True for a sender that looks like a person's phone number, as opposed to a business.

    Businesses send from names ("Capitec"), short codes (up to 6 digits) or long
    bulk-messaging numbers (13 digits or more). A number of 7 to 12 digits looks
    like someone's phone, and the export often does not say whether that person
    is a saved contact, so those messages are left out to keep conversations private.
    """
    if re.search(r"[A-Za-z]", sender):
        return False
    digits = re.sub(r"\D", "", sender)
    return 7 <= len(digits) <= 12


def mask_for_labelling(text: str, names: list[str]) -> str:
    """Stronger masking than the engine uses, because this file is read by people.

    Email addresses, the owner's names, and any token with five or more digits (order numbers, student
    numbers, references) are masked. Rand amounts and phone numbers are kept, because the gate reads them.
    """
    text = EMAIL_PATTERN.sub("[email withheld]", text)
    for name in names:
        text = re.sub(rf"\b{re.escape(name)}\b", "[name]", text, flags=re.I)

    def mask(match: re.Match) -> str:
        token = match.group()
        if sum(character.isdigit() for character in token) < 5 or AMOUNT_PATTERN.fullmatch(token) or PHONE_PATTERN.fullmatch(token):
            return token
        return "[id withheld]"

    return TOKEN.sub(mask, text)


def collect(export: Path, per_sender: int, limit: int, seed: int = 1, names: list[str] | None = None) -> list[tuple[str, str]]:
    """Returns (text, sender) pairs: received, from a business sender, no one-time codes, numbers masked."""
    by_sender: dict[str, list[str]] = defaultdict(list)
    seen = set()
    for sms in ET.parse(export).getroot().iter("sms"):
        text = " ".join((sms.get("body") or "").split())
        sender = sms.get("address") or ""
        if sms.get("type") != RECEIVED or (sms.get("contact_name") or "").strip().lower() not in NOT_A_CONTACT:
            continue
        if looks_personal(sender):
            continue
        if not text or is_one_time_code(text):
            continue
        text = mask_for_labelling(redact(text), names or [])
        shape = MONTHS.sub("month", re.sub(r"\d+", "0", text.lower()))  # the same notice with other amounts or dates counts once
        if shape in seen:
            continue
        seen.add(shape)
        by_sender[sender or "unknown"].append(text)
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
    parser.add_argument("--mask", default="", help="Comma-separated words to mask, such as your first name and surname")
    args = parser.parse_args()
    sample = collect(args.export, args.per_sender, args.limit, names=[word.strip() for word in args.mask.split(",") if word.strip()])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"?\t{text}\t{sender}\n" for text, sender in sample), encoding="utf-8", newline="\n")
    print(f"Wrote {len(sample)} messages to {args.output}. Replace each ? with scam or benign, then run calibrate.py on it.")


if __name__ == "__main__":
    main()
