"""Worktree model: parsing of `git worktree list --porcelain` + git status."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import naming
from .gitrunner import GitRunner
from .repo import RepoContext


@dataclass
class Worktree:
    path: Path
    branch: Optional[str]          # short branch name, or None if detached/bare
    head: Optional[str]            # sha
    is_bare: bool = False
    is_detached: bool = False
    prunable: bool = False
    locked: bool = False

    # Derived (filled in enrich):
    rel_path: str = ""
    classification: Optional[naming.Classification] = None
    exists: bool = True
    dirty: Optional[bool] = None
    ahead: Optional[int] = None
    behind: Optional[int] = None
    upstream: Optional[str] = None


def _parse_porcelain(text: str) -> List[Worktree]:
    worktrees: List[Worktree] = []
    cur: dict = {}

    def flush():
        if not cur:
            return
        branch = cur.get("branch")
        if branch and branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/"):]
        worktrees.append(
            Worktree(
                path=Path(cur["worktree"]),
                branch=branch,
                head=cur.get("HEAD"),
                is_bare="bare" in cur,
                is_detached="detached" in cur,
                prunable="prunable" in cur,
                locked="locked" in cur,
            )
        )
        cur.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        if " " in line:
            key, val = line.split(" ", 1)
        else:
            key, val = line, True
        cur[key] = val
    flush()
    return worktrees


def list_worktrees(git: GitRunner, repo: RepoContext, *, with_status: bool = True) -> List[Worktree]:
    raw = git.out(["worktree", "list", "--porcelain"], cwd=repo.bare)
    wts = _parse_porcelain(raw)
    for wt in wts:
        _enrich(git, repo, wt, with_status=with_status)
    return wts


def _rel(repo_root: Path, path: Path) -> str:
    try:
        rel = os.path.relpath(str(path), str(repo_root))
    except ValueError:
        rel = str(path)
    return rel.replace("\\", "/")


def _enrich(git: GitRunner, repo: RepoContext, wt: Worktree, *, with_status: bool) -> None:
    wt.rel_path = _rel(repo.root, wt.path)
    wt.exists = wt.path.exists()

    if wt.is_bare:
        return

    wt.classification = naming.classify(wt.rel_path, wt.branch)

    if not with_status or not wt.exists:
        return

    # Dirty / clean.
    status = git.run(["status", "--porcelain"], cwd=wt.path, check=False, mutating=False)
    wt.dirty = bool(status.stdout.strip())

    if wt.branch:
        up = git.run(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{wt.branch}@{{upstream}}"],
            cwd=wt.path,
            check=False,
            mutating=False,
        )
        if up.returncode == 0 and up.stdout.strip():
            wt.upstream = up.stdout.strip()
            counts = git.run(
                ["rev-list", "--left-right", "--count", f"{wt.upstream}...HEAD"],
                cwd=wt.path,
                check=False,
                mutating=False,
            )
            if counts.returncode == 0 and counts.stdout.strip():
                parts = counts.stdout.split()
                if len(parts) == 2:
                    wt.behind = int(parts[0])
                    wt.ahead = int(parts[1])
