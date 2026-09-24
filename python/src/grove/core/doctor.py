"""Worktree diagnostics and hygiene (doctor command)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from . import config, naming, ops
from . import platform as plat
from .gitrunner import GitRunner
from .model import Worktree, list_worktrees
from .repo import RepoContext, has_git_pointer, write_git_pointer

AUTO = "auto"
MANUAL = "manual"


@dataclass
class Issue:
    kind: str                       # orphan | upstream | release-format | naming | ticket | nested
                                    # | git-pointer | stale-lock | lock | stale-tmp | identity
                                    # | bare-head | parking-branch
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

    # --- missing root .git pointer ---------------------------------------- #
    if not has_git_pointer(repo.root):
        def _fix_pointer():
            write_git_pointer(repo.root)
        issues.append(Issue(
            kind="git-pointer", severity=AUTO, target=".git",
            message="missing root .git pointer (gitdir: ./.bare)",
            action="write .git → gitdir: ./.bare", fix=_fix_pointer,
        ))

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

    issues.extend(_bare_head(git, repo, existing))
    issues.extend(_worktree_paths(git, repo))
    issues.extend(_hygiene(git, repo, existing))
    return issues


# --------------------------------------------------------------------------- #
# Bare HEAD -> base, and the legacy parking branch (before python 0.10.0)
# --------------------------------------------------------------------------- #

def _worktree_paths(git: GitRunner, repo: RepoContext) -> List[Issue]:
    """The repo's worktree paths don't match `relative_worktrees`."""
    from . import worktree_paths as wp
    action = wp.drift(git, repo)
    if not action:
        return []
    want = "relative" if action == "enable" else "absolute"
    if action == "enable" and wp.git_version(git) < wp.MIN_GIT:
        return [Issue(
            kind="worktree-paths", severity=MANUAL, target=".bare",
            message=(f"relative_worktrees = true, but it needs git >= "
                     f"{wp.MIN_GIT[0]}.{wp.MIN_GIT[1]}"),
            action="upgrade git, or `gwt config set relative_worktrees false`",
        )]
    return [Issue(
        kind="worktree-paths", severity=AUTO, target=".bare",
        message=f"worktree paths don't match relative_worktrees ({want} expected)",
        action=f"convert the worktrees to {want} paths",
        fix=(lambda: wp.enable(git, repo)) if action == "enable" else (lambda: wp.disable(git, repo)),
    )]


def _bare_head(git: GitRunner, repo: RepoContext, existing: List[Worktree]) -> List[Issue]:
    issues: List[Issue] = []
    base = config.DEFAULT_BASE
    if not git.ok(["rev-parse", "--verify", "-q", f"refs/heads/{base}"], cwd=repo.bare):
        return issues                      # no local base: nothing sensible to point at
    head = git.run(["symbolic-ref", "-q", "HEAD"], cwd=repo.bare,
                   check=False, mutating=False).stdout.strip()
    if head != f"refs/heads/{base}":
        def _fix_head():
            git.run(["symbolic-ref", "HEAD", f"refs/heads/{base}"], cwd=repo.bare)
        issues.append(Issue(
            kind="bare-head", severity=AUTO, target=".bare/HEAD",
            message=f"bare HEAD points at {head or '(detached)'}, not the base",
            action=f"point it at refs/heads/{base}", fix=_fix_head,
        ))

    park = config.PARKING_BRANCH
    if park == base or not git.ok(["rev-parse", "--verify", "-q", f"refs/heads/{park}"],
                                  cwd=repo.bare):
        return issues
    in_use = any(w.branch == park for w in existing)
    merged = git.ok(["merge-base", "--is-ancestor", park, base], cwd=repo.bare)
    if merged and not in_use:
        def _drop_parking():
            git.run(["branch", "-D", park], cwd=repo.bare)
        issues.append(Issue(
            kind="parking-branch", severity=AUTO, target=park,
            message="legacy internal parking branch (not needed since 0.10.0)",
            action=f"delete branch {park} (no commits outside {base})", fix=_drop_parking,
        ))
    else:
        why = "it has a worktree" if in_use else f"it has commits that {base} doesn't"
        issues.append(Issue(
            kind="parking-branch", severity=MANUAL, target=park,
            message=f"legacy internal parking branch; not deleted because {why}",
            action="review it; delete it with 'git branch -D' once nothing is lost",
        ))
    return issues


# --------------------------------------------------------------------------- #
# Repository hygiene: leftover locks / temp objects, author identity
# --------------------------------------------------------------------------- #

# A lock younger than this is assumed to be in use.
LOCK_MIN_AGE = 60
# A lock older than this is orphaned even if some git process is running
# (no normal git operation holds a lock this long).
LOCK_HARD_AGE = 600
_TMP_OBJECT_GLOBS = ("tmp_obj_*", "??/tmp_obj_*", "pack/tmp_pack_*", "pack/tmp_idx_*")


def _git_running() -> Optional[bool]:
    """Indirection so tests can pin the process state."""
    return plat.git_process_running()


def _find_locks(bare: Path) -> List[Path]:
    locks: List[Path] = []
    objects = bare / "objects"
    for dirpath, dirnames, filenames in os.walk(bare):
        d = Path(dirpath)
        if d == objects:
            # skip the loose-object fan-out (00..ff): thousands of files, no locks
            dirnames[:] = [n for n in dirnames if len(n) != 2]
        locks.extend(d / f for f in filenames if f.endswith(".lock"))
    return sorted(locks)


def _find_tmp_objects(bare: Path) -> List[Path]:
    objects = bare / "objects"
    found = {p for g in _TMP_OBJECT_GLOBS for p in objects.glob(g) if p.is_file()}
    return sorted(found)


def _age(path: Path, now: float) -> Optional[float]:
    try:
        return now - path.stat().st_mtime
    except OSError:
        return None  # vanished meanwhile


def _is_stale(age: float, running: Optional[bool]) -> bool:
    if age >= LOCK_HARD_AGE:
        return True
    return age >= LOCK_MIN_AGE and running is False


def _unlink_all(paths: List[Path]) -> Callable[[], None]:
    def _fix():
        for p in paths:
            try:
                p.unlink()
            except FileNotFoundError:
                pass
    return _fix


def _hygiene(git: GitRunner, repo: RepoContext, existing: List[Worktree]) -> List[Issue]:
    issues: List[Issue] = []
    now = time.time()
    locks = _find_locks(repo.bare)
    tmps = _find_tmp_objects(repo.bare)
    running = _git_running() if (locks or tmps) else None

    def rel(p: Path) -> str:
        return os.path.relpath(str(p), str(repo.root)).replace("\\", "/")

    for lock in locks:
        age = _age(lock, now)
        if age is None:
            continue
        if _is_stale(age, running):
            issues.append(Issue(
                kind="stale-lock", severity=AUTO, target=rel(lock),
                message=f"orphaned git lock ({int(age)}s old)",
                action="delete the lock file", fix=_unlink_all([lock]),
            ))
        else:
            issues.append(Issue(
                kind="lock", severity=MANUAL, target=rel(lock),
                message=f"git lock present ({int(age)}s old); a git command may be using it",
                action="re-run doctor when no git command is running",
            ))

    stale_tmp = [p for p in tmps if (a := _age(p, now)) is not None and _is_stale(a, running)]
    if stale_tmp:
        issues.append(Issue(
            kind="stale-tmp", severity=AUTO, target=rel(repo.bare / "objects"),
            message=f"{len(stale_tmp)} leftover temporary object file(s) from an interrupted git command",
            action="delete them", fix=_unlink_all(stale_tmp),
        ))

    # Author identity: `git var GIT_AUTHOR_IDENT` fails exactly when a commit
    # would fail with "Author identity unknown" (honours includeIf/zones).
    for w in existing:
        r = git.run(["var", "GIT_AUTHOR_IDENT"], cwd=w.path, check=False, mutating=False)
        if r.returncode != 0:
            issues.append(Issue(
                kind="identity", severity=MANUAL, target=w.rel_path,
                message="no git author identity: commits here will fail ('Author identity unknown')",
                action="set user.name/user.email (git config, or a zone with 'gwt ssh add')",
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
# Leftover locks go first: they can make every other git-based fix fail.
_FIX_ORDER = {"stale-lock": 0, "stale-tmp": 0, "bare-head": 0.5, "parking-branch": 0.6,
              "worktree-paths": 0.7,
              "upstream": 1, "naming": 2, "release-format": 3, "orphan": 4}


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
