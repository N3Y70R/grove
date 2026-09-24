"""Worktree model: parsing of `git worktree list --porcelain` + git status."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import config, naming
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
    # Internal admin dir (.bare/worktrees/<name>), relative to the repo root.
    # git names it after the LAST path component, so it can't be derived from
    # rel_path; exposing it lets tools on another mount build GIT_DIR.
    gitdir: Optional[str] = None
    # True when the branch has no commits outside the base (so `remove --merged`
    # would sweep it). Note: a brand-new branch with no commits of its own also
    # counts. None for the base itself, detached/bare, or when not computed.
    merged: Optional[bool] = None
    # What ahead/behind are measured against: the upstream (e.g. "origin/main")
    # or, for a branch with no upstream yet, the repo base (e.g. "main").
    compared_to: Optional[str] = None


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
    admin = _admin_dirs(repo)
    base = config.DEFAULT_BASE
    base_ok = with_status and git.ok(["rev-parse", "--verify", "-q", f"refs/heads/{base}"],
                                     cwd=repo.bare)
    for wt in wts:
        if not wt.is_bare:
            wt.gitdir = admin.get(os.path.normpath(str(wt.path)))
        _enrich(git, repo, wt, with_status=with_status)
        if base_ok and wt.branch and wt.branch != base:
            wt.merged = git.ok(["merge-base", "--is-ancestor", wt.branch, base], cwd=repo.bare)
            if wt.upstream is None:
                _count_vs(git, repo, wt, base)
    return wts


def _count_vs(git: GitRunner, repo: RepoContext, wt: Worktree, ref: str) -> None:
    """ahead/behind of wt.branch against `ref` (used when there is no upstream)."""
    r = git.run(["rev-list", "--left-right", "--count", f"{ref}...{wt.branch}"],
                cwd=repo.bare, check=False, mutating=False)
    parts = r.stdout.split() if r.returncode == 0 else []
    if len(parts) == 2:
        wt.behind, wt.ahead = int(parts[0]), int(parts[1])
        wt.compared_to = ref


def _localize(repo: RepoContext, wt: Worktree) -> bool:
    """Map a worktree recorded under another mount point to this one.

    git records absolute paths, so when the repo is seen from another path
    (container, VM) `git worktree list` reports the ORIGINAL location, which
    doesn't exist here. Find the local folder: the shortest trailing part of the
    recorded path that exists under repo.root and whose `.git` file points at
    this worktree's admin dir. Returns True if found (path/rel_path fixed).
    """
    if not wt.gitdir:
        return False
    admin_name = Path(wt.gitdir).name
    parts = Path(wt.path).parts
    for i in range(len(parts) - 1, 0, -1):
        cand = repo.root.joinpath(*parts[i:])
        gfile = cand / ".git"
        try:
            text = gfile.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text.startswith("gitdir:") and Path(text[len("gitdir:"):].strip()).name == admin_name:
            wt.path = cand
            wt.rel_path = _rel(repo.root, cand)
            return True
    return False


def _admin_dirs(repo: RepoContext) -> dict:
    """Map worktree path -> its admin dir (relative to the repo root).

    Each `.bare/worktrees/<name>/gitdir` file holds the path of `<worktree>/.git`
    as git recorded it — the same form `git worktree list` prints — so matching
    works even when the repo is viewed from another mount.
    """
    out = {}
    base = repo.bare / "worktrees"
    if not base.is_dir():
        return out
    for d in base.iterdir():
        try:
            recorded = (d / "gitdir").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not recorded:
            continue
        wt_path = recorded if os.path.isabs(recorded) else os.path.join(str(d), recorded)
        out[os.path.normpath(os.path.dirname(wt_path))] = _rel(repo.root, d)
    return out


def worktree_dict(wt: Worktree) -> dict:
    """The JSON/MCP view of a worktree (single source for CLI and MCP)."""
    cls = wt.classification
    return {
        "path": str(wt.path),
        "rel_path": wt.rel_path,
        "branch": wt.branch,
        "bare": wt.is_bare,
        "detached": wt.is_detached,
        "prunable": wt.prunable,
        "exists": wt.exists,
        "ticket": cls.ticket if cls else None,
        "kind": cls.kind if cls else None,
        "type": cls.type if cls else None,
        "dirty": wt.dirty,
        "ahead": wt.ahead,
        "behind": wt.behind,
        "upstream": wt.upstream,
        "gitdir": wt.gitdir,
        "merged": wt.merged,
        "compared_to": wt.compared_to,
    }


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

    # Seen from another mount: the recorded path doesn't exist here, but the
    # worktree does. Not an orphan — never let it look prunable.
    if not wt.exists and _localize(repo, wt):
        wt.exists = True
        wt.prunable = False

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
            wt.compared_to = wt.upstream
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
