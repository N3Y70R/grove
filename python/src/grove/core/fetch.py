"""Fetch operation: bring what's new on origin and report where each worktree
stands — WITHOUT touching any worktree.

This is the safe counterpart of `reset` (which discards local work): it only
updates the `origin/*` refs, then reports ahead/behind per worktree so the user
decides how to integrate (e.g. `git merge --ff-only` inside the worktree).
"""

from __future__ import annotations

from typing import List

from .compare import status_word
from .gitrunner import GitRunner
from .model import list_worktrees
from .repo import RepoContext

Step = lambda m: None  # noqa: E731


def fetch(git: GitRunner, repo: RepoContext, *, prune: bool = False, step=Step) -> List[dict]:
    """`git fetch origin` (optionally `--prune`) and a per-worktree status."""
    args = ["fetch", "origin"] + (["--prune"] if prune else [])
    step("Fetching from origin" + (" (pruning deleted branches)" if prune else ""))
    git.run(args, cwd=repo.bare)

    rows: List[dict] = []
    for wt in list_worktrees(git, repo, with_status=True):
        if wt.is_bare:
            continue
        ahead, behind = wt.ahead, wt.behind
        rows.append({
            "worktree": wt.rel_path,
            "branch": wt.branch,
            "compared_to": wt.compared_to,
            "ahead": ahead,
            "behind": behind,
            "status": status_word(ahead, behind) if ahead is not None and behind is not None else None,
            "dirty": wt.dirty,
        })
    return rows
