"""One runtime, with its own world, for each person looked after.

Incidents, reviews, blocked senders, disputes and the rest live here, saved to each person's own
file (core/store.py), and never cross from one person to another. The default runtime serves the plain console and offline use.
"""
from threading import Lock

from core.runtime import TriageRuntime
from domain.tools import World

_lock = Lock()
_runtimes: dict[str, TriageRuntime] = {}
_default: TriageRuntime | None = None


def runtime_for(person_id: str) -> TriageRuntime:
    """This person's runtime, created empty the first time it is needed."""
    with _lock:
        if person_id not in _runtimes:
            _runtimes[person_id] = TriageRuntime(world=World(), person_id=person_id)  # loads the person's saved state
        return _runtimes[person_id]


def default_runtime() -> TriageRuntime:
    """The shared runtime used when no person is named. Only reachable in development mode."""
    global _default
    with _lock:
        if _default is None:
            _default = TriageRuntime()
        return _default


def all_runtimes() -> list[TriageRuntime]:
    """Every runtime that exists, for jobs that sweep them all."""
    with _lock:
        return [*_runtimes.values(), *([_default] if _default else [])]


def forget_everyone() -> None:
    """Drop every person's runtime. For tests."""
    with _lock:
        _runtimes.clear()
