"""Label a collected message file one message at a time: s = scam, b = benign, u = unsure, q = quit.

Every answer is saved immediately, so you can stop and carry on later. Only
lines still marked `?` are shown.
"""
import argparse
from pathlib import Path

ANSWERS = {"s": "scam", "b": "benign", "u": "unsure"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, nargs="?", default=Path("data/sa_messages.tsv"))
    args = parser.parse_args()
    lines = args.file.read_text(encoding="utf-8").splitlines()
    waiting = [index for index, line in enumerate(lines) if line.startswith("?\t")]
    print(f"{len(waiting)} messages to label. s = scam, b = benign, u = unsure, q = quit.\n")
    for count, index in enumerate(waiting, start=1):
        _, text, *rest = lines[index].split("\t")
        print(f"[{count}/{len(waiting)}] from {rest[0] if rest else 'unknown'}\n  {text}")
        answer = ""
        while answer not in ANSWERS and answer != "q":
            answer = input("  s / b / u / q: ").strip().lower()
        if answer == "q":
            break
        lines[index] = ANSWERS[answer] + lines[index][1:]
        args.file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print()
    left = sum(line.startswith("?\t") for line in lines)
    print(f"Saved. {left} still to label." if left else "All labelled. Run calibrate.py on the file.")


if __name__ == "__main__":
    main()
