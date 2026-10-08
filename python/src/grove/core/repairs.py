"""Shared execution accounting for doctor callbacks; verification stays in each doctor."""

from typing import Callable, Iterable
from .errors import WtError


def execute(actions: Iterable[tuple[str, str, Callable]]) -> dict:
    attempted = 0
    completed = []
    failures = []
    seen = set()
    for check, target, callback in actions:
        if id(callback) in seen:
            continue
        seen.add(id(callback))
        attempted += 1
        try:
            result = callback()
            if result is False:
                failures.append({"check": check, "target": target,
                                 "message": ("Unlock/load the key in a terminal, then diagnose again." if check == "agent" else
                                             "Repair did not complete; review the remaining diagnosis.")})
            else:
                completed.append((check, target))
        except (WtError, OSError) as exc:
            from .redaction import redact
            failures.append({"check": check, "target": target, "message": redact(str(exc))})
    return {"attempted": attempted, "completed": completed, "failures": failures}
