"""Reset operation (formerly "sync"): resets a worktree to its origin branch.

Intended for branches that are regenerated/force-pushed (e.g. the test
integration branch): fetches the remote version and resets the worktree,
DISCARDING local commits and changes. Exposed as `gwt reset` / `grove_reset`;
the old `sync` names remain as deprecated aliases.
"""

from __future__ import annotations

from typing import Optional

from .errors import ValidationError
from .gitrunner import GitRunner
from .model import Worktree
from .repo import RepoContext

Step = lambda m: None  # noqa: E731


def reset_worktree(
    git: GitRunner,
    repo: RepoContext,
    wt: Worktree,
    *,
    clean: bool = False,
    step=Step,
) -> str:
    """fetch + reset --hard of the worktree to its remote branch. Returns the upstream used."""
    if not wt.branch:
        raise ValidationError(
            f"'{wt.rel_path}' is in detached HEAD; it cannot be reset."
        )

    upstream = wt.upstream or f"origin/{wt.branch}"
    if not upstream.startswith("origin/"):
        raise ValidationError(
            f"Branch '{wt.branch}' does not track an origin branch; there is nothing to reset to."
        )
    remote_branch = upstream[len("origin/"):]

    step(f"Updating {upstream}")
    git.run(["fetch", "origin", remote_branch], cwd=repo.bare)

    step(f"Resetting {wt.rel_path} to {upstream}")
    git.run(["reset", "--hard", upstream], cwd=wt.path)

    if clean:
        step("Cleaning untracked files (git clean -fd)")
        git.run(["clean", "-fd"], cwd=wt.path)

    return upstream


def reset_losses(wt: Worktree) -> list:
    """What a reset would discard, worded by what ahead is measured against."""
    losses = []
    if wt.ahead:
        if wt.upstream:
            losses.append(f"{wt.ahead} local commit(s) not pushed")
        else:
            ref = wt.compared_to or "the base"
            losses.append(f"{wt.ahead} commit(s) ahead of {ref} with no upstream (may not be pushed)")
    if wt.dirty:
        losses.append("uncommitted changes")
    return losses


# Deprecated name, kept for backward compatibility.
sync_worktree = reset_worktree
