"""Opt-in relative worktree paths (`relative_worktrees = true` in grove.toml).

By default git records absolute paths in each worktree's `.git` file and in
`.bare/worktrees/<name>/gitdir`, so a repo seen from another mount (container,
VM) can't use git inside its worktrees. git >= 2.48 can record relative paths
instead. It is OFF by default because it is not backward compatible: git sets
`extensions.relativeWorktrees`, and older git (and libgit2 < 1.9.4 tools)
refuse to open the repository at all.

Enabling sets `worktree.useRelativePaths` in the bare — so EVERY later
`git worktree add/move/repair` (grove's or the user's) records relative paths —
and converts the existing worktrees. Disabling converts them back to absolute
and removes the extension so older git works again.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from . import config
from .errors import ValidationError
from .gitrunner import GitRunner
from .model import list_worktrees
from .repo import RepoContext

MIN_GIT: Tuple[int, int] = (2, 48)


def git_version(git: GitRunner) -> Tuple[int, ...]:
    """(major, minor, patch) of the git in use; (0,) if it can't be read."""
    r = git.run(["--version"], check=False, mutating=False)
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", getattr(r, "stdout", "") or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else (0,)


def _require_support(git: GitRunner) -> None:
    v = git_version(git)
    if v < MIN_GIT:
        found = ".".join(map(str, v)) if v != (0,) else "unknown"
        raise ValidationError(
            f"relative_worktrees needs git >= {MIN_GIT[0]}.{MIN_GIT[1]} (found {found}). "
            f"Upgrade git, or keep the default absolute paths.")


def _worktree_dirs(git: GitRunner, repo: RepoContext) -> List[Path]:
    return [w.path for w in list_worktrees(git, repo, with_status=False)
            if not w.is_bare and w.exists]


def _is_relative(wt: Path) -> Optional[bool]:
    try:
        text = (wt / ".git").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    return not os.path.isabs(text[len("gitdir:"):].strip())


def _cfg(git: GitRunner, repo: RepoContext, key: str) -> str:
    return git.run(["config", "--get", key], cwd=repo.bare, check=False,
                   mutating=False).stdout.strip().lower()


def drift(git: GitRunner, repo: RepoContext) -> Optional[str]:
    """'enable' / 'disable' when the repo's real state doesn't match the setting."""
    rel = [_is_relative(p) for p in _worktree_dirs(git, repo)]
    use = _cfg(git, repo, "worktree.useRelativePaths") == "true"
    if config.RELATIVE_WORKTREES:
        return None if use and all(r is not False for r in rel) else "enable"
    ext = _cfg(git, repo, "extensions.relativeworktrees") == "true"
    return "disable" if (use or ext or any(r is True for r in rel)) else None


def enable(git: GitRunner, repo: RepoContext) -> None:
    _require_support(git)
    git.run(["config", "worktree.useRelativePaths", "true"], cwd=repo.bare)
    dirs = [str(p) for p in _worktree_dirs(git, repo)]
    if dirs:
        git.run(["worktree", "repair", "--relative-paths", *dirs], cwd=repo.bare)


def disable(git: GitRunner, repo: RepoContext) -> None:
    git.run(["config", "--unset", "worktree.useRelativePaths"], cwd=repo.bare, check=False)
    dirs = [str(p) for p in _worktree_dirs(git, repo)]
    if dirs and git_version(git) >= MIN_GIT:
        git.run(["worktree", "repair", "--no-relative-paths", *dirs], cwd=repo.bare)
    if not any(_is_relative(Path(d)) for d in dirs):
        # only once every worktree is absolute again, so older git can open the repo
        git.run(["config", "--unset", "extensions.relativeWorktrees"], cwd=repo.bare,
                check=False)


def apply(git: GitRunner, repo: RepoContext) -> Optional[str]:
    """Bring the repo in line with the setting. Returns the action taken, if any."""
    action = drift(git, repo)
    if action == "enable":
        enable(git, repo)
    elif action == "disable":
        disable(git, repo)
    return action


def apply_if_configured(git: GitRunner, repo: RepoContext, warn=lambda m: None) -> Optional[str]:
    """For setup/convert: honour a profile's relative_worktrees without failing the
    whole operation on an old git (it warns instead; `doctor` reports it later)."""
    if not config.RELATIVE_WORKTREES:
        return None
    try:
        return apply(git, repo)
    except ValidationError as e:
        warn(str(e))
        return None


def set_relative(git: GitRunner, repo: RepoContext, value: bool) -> Optional[str]:
    """`config set relative_worktrees`: check support BEFORE writing, then apply."""
    if value:
        _require_support(git)
    config.set_repo_value(repo.bare, "relative_worktrees", "true" if value else "false")
    config.RELATIVE_WORKTREES = value
    return apply(git, repo)
