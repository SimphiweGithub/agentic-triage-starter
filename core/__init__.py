"""Reusable deterministic runtime components."""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Read NAME=value lines into the environment. Variables already set in the terminal win."""
    if os.getenv("KINGUARD_SKIP_ENV_FILE") == "1" or not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


load_env_file()
