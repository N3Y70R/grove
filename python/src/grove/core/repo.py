"""Detection and context of the managed repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import UsageError


@dataclass
class RepoContext:
    root: Path           # repo folder (contains .bare/)
    bare: Path           # .bare/
    name: str            # name of the repo folder
    base: Optional[str] = None   # base branch actually used (set by setup)


def find_repo(start: Optional[Path] = None) -> RepoContext:
    """Searches upward for the managed repo folder (the one containing .bare/).

    Raises UsageError if not found.
    """
    cur = (Path(start) if start else Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        bare = candidate / ".bare"
        if bare.is_dir():
            return RepoContext(root=candidate, bare=bare, name=candidate.name)
    raise UsageError(
        "No managed repo (.bare/) found from this directory. "
        "Use 'wt setup <url>' to create one, or move into a managed repo."
    )
