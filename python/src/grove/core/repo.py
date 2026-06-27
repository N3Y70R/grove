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


GIT_POINTER_CONTENT = "gitdir: ./.bare\n"


def has_git_pointer(root: Path) -> bool:
    """True if <root>/.git is a file pointing at the bare repo."""
    p = Path(root) / ".git"
    try:
        return p.is_file() and p.read_text(encoding="utf-8").strip().startswith("gitdir:")
    except OSError:
        return False


def write_git_pointer(root: Path) -> bool:
    """Create <root>/.git -> 'gitdir: ./.bare' if absent. Returns True if created.

    This makes plain `git` work from the repo root (worktree list, fetch, …);
    grove's own commands don't need it. Never clobbers an existing `.git`.
    """
    p = Path(root) / ".git"
    if p.exists():
        return False
    p.write_text(GIT_POINTER_CONTENT, encoding="utf-8")
    return True


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
