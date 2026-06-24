"""Sync operation: re-syncs a worktree with the origin state.

Intended for branches that are regenerated/force-pushed (e.g. the test
integration branch): fetches the remote version and resets the worktree, discarding local changes.
"""

from __future__ import annotations

from typing import Optional

from .errors import ValidationError
from .gitrunner import GitRunner
from .model import Worktree
from .repo import RepoContext

Step = lambda m: None  # noqa: E731


def sync_worktree(
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
            f"'{wt.rel_path}' is in detached HEAD; it cannot be synced."
        )

    upstream = wt.upstream or f"origin/{wt.branch}"
    if not upstream.startswith("origin/"):
        raise ValidationError(
            f"Branch '{wt.branch}' does not track an origin branch; there is nothing to sync with."
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
