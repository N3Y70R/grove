"""Worktree diagnostics and hygiene (doctor command)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from . import config, naming, ops
from .gitrunner import GitRunner
from .model import Worktree, list_worktrees
from .repo import RepoContext

AUTO = "auto"
MANUAL = "manual"


@dataclass
class Issue:
    kind: str                       # orphan | upstream | release-format | naming | ticket | nested
    severity: str                   # AUTO | MANUAL
    target: str                     # affected folder/branch
    message: str                    # description of the problem
    action: str                     # what would be done to fix it
    fix: Optional[Callable[[], None]] = field(default=None, repr=False)


def _allowed_top() -> set:
    """Valid top-level folders. Computed at runtime: the repo config
    has already been loaded and the base branch may vary by profile (main, production, ...)."""
    return (
        set(config.TYPE_FOLDERS)
        | {config.TEMP_DIR}
        | set(config.SPECIAL_WORKTREES)
        | {config.DEFAULT_BASE, config.PARKING_BRANCH}
    )


def _top(rel_path: str) -> str:
    return rel_path.replace("\\", "/").split("/", 1)[0]


def diagnose(git: GitRunner, repo: RepoContext) -> List[Issue]:
    wts = list_worktrees(git, repo, with_status=True)
    issues: List[Issue] = []
    ALLOWED_TOP = _allowed_top()

    real = [w for w in wts if not w.is_bare]

    # --- orphans ---------------------------------------------------------- #
    def _prune():
        git.run(["worktree", "prune"], cwd=repo.bare)

    for w in real:
        if w.prunable or not w.exists:
            issues.append(Issue(
                kind="orphan", severity=AUTO, target=w.rel_path,
                message="record with no directory on disk",
                action="git worktree prune", fix=_prune,
            ))

    # --- nested worktrees (one inside another) ---------------------------- #
    existing = [w for w in real if w.exists]
    for w in existing:
        for other in existing:
            if w is other:
                continue
            try:
                w.path.resolve().relative_to(other.path.resolve())
                issues.append(Issue(
                    kind="nested", severity=MANUAL, target=w.rel_path,
                    message=f"nested inside {other.rel_path}",
                    action="relocate manually to the correct level",
                ))
                break
            except ValueError:
                pass

    # --- structure: release-format / naming ------------------------------- #
    for w in existing:
        if w.branch is None:
            continue
        top = _top(w.rel_path)

        # Old release format (hyphen): release-vX.Y.Z -> release/vX.Y.Z
        legacy = w.branch.startswith("release-") or top.startswith("release-")
        if legacy:
            version = w.branch[len("release-"):] if w.branch.startswith("release-") else top[len("release-"):]
            new_branch = config.RELEASE_FORMAT.format(version=version)
            new_rel = new_branch
            issues.append(Issue(
                kind="release-format", severity=AUTO, target=w.rel_path,
                message="release format with hyphen",
                action=f"rename to {new_rel}",
                fix=_make_rename_fix(git, repo, w, new_branch, new_rel),
            ))
            continue

        # Naming: top outside the allowed folders.
        if top not in ALLOWED_TOP:
            cls = naming.parse_origin_branch(w.branch)
            if cls.kind in ("ticket", "release") and "/" in w.branch:
                # The branch is of an ALLOWED type but misplaced -> move (auto).
                issues.append(Issue(
                    kind="naming", severity=AUTO, target=w.rel_path,
                    message=f"folder outside convention (branch {w.branch})",
                    action=f"move to {w.branch}",
                    fix=_make_move_fix(git, repo, w, w.branch),
                ))
            elif "/" in w.branch and w.branch.split("/", 1)[1].strip():
                # Structurally valid (<segment>/<...>) but the type is NOT in
                # allowed_types (e.g. chore/...). It is reported, NOT fixed.
                issues.append(Issue(
                    kind="type-not-allowed", severity=MANUAL, target=w.rel_path,
                    message=f"type '{top}' is not in allowed_types ({', '.join(config.TICKET_TYPES)})",
                    action="review (not moved automatically; add the type to allowed_types if appropriate)",
                ))
            else:
                issues.append(Issue(
                    kind="naming", severity=MANUAL, target=w.rel_path,
                    message="folder and branch outside convention",
                    action="relocate with judgment (unconventional branch)",
                ))

    # --- folder ticket != branch ticket (does not apply if tickets = off) - #
    for w in (existing if config.TICKETS != "off" else []):
        if w.branch is None:
            continue
        folder_ticket = naming.extract_ticket(w.rel_path)
        branch_ticket = naming.extract_ticket(w.branch)
        if folder_ticket and branch_ticket and folder_ticket != branch_ticket:
            issues.append(Issue(
                kind="ticket", severity=MANUAL, target=w.rel_path,
                message=f"folder ticket ({folder_ticket}) ≠ branch ticket ({branch_ticket})",
                action="review and fix manually",
            ))

    # --- missing/incorrect upstream for origin branches ------------------- #
    for w in existing:
        if w.branch is None:
            continue
        expected = f"origin/{w.branch}"
        if ops.origin_branch_exists(git, repo, w.branch) and w.upstream != expected:
            issues.append(Issue(
                kind="upstream", severity=AUTO, target=w.rel_path,
                message=f"no correct upstream (expected {expected})",
                action=f"set-upstream {expected}",
                fix=_make_upstream_fix(git, repo, w.branch, expected),
            ))

    return issues


def _make_upstream_fix(git: GitRunner, repo: RepoContext, branch: str, expected: str):
    # Runs from the bare with the branch name: independent of the worktree path
    # (so it does not break if another fix moved the folder beforehand).
    def _fix():
        git.run(["branch", f"--set-upstream-to={expected}", branch], cwd=repo.bare)
    return _fix


def _make_move_fix(git: GitRunner, repo: RepoContext, w: Worktree, new_rel: str):
    def _fix():
        new_abs = repo.root / Path(new_rel)
        new_abs.parent.mkdir(parents=True, exist_ok=True)
        git.run(["worktree", "move", str(w.path), str(new_abs)], cwd=repo.bare)
    return _fix


def _make_rename_fix(git: GitRunner, repo: RepoContext, w: Worktree, new_branch: str, new_rel: str):
    def _fix():
        # Rename the branch and move the folder to the convention.
        git.run(["branch", "-m", w.branch, new_branch], cwd=repo.bare)
        new_abs = repo.root / Path(new_rel)
        new_abs.parent.mkdir(parents=True, exist_ok=True)
        git.run(["worktree", "move", str(w.path), str(new_abs)], cwd=repo.bare)
    return _fix


# Application order: upstream before moving/renaming folders; prune last.
_FIX_ORDER = {"upstream": 1, "naming": 2, "release-format": 3, "orphan": 4}


def apply(issues: List[Issue]) -> int:
    """Runs the available automatic fixes. Returns how many it applied."""
    fixables = [i for i in issues if i.fix is not None]
    fixables.sort(key=lambda i: _FIX_ORDER.get(i.kind, 9))
    applied = 0
    seen = set()
    for issue in fixables:
        key = id(issue.fix)
        if key in seen:          # avoids repeating the same global fix (e.g. prune)
            continue
        seen.add(key)
        issue.fix()
        applied += 1
    return applied
