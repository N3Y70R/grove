"""Convert an existing normal clone into the grove bare + worktrees model.

Two modes (see docs/DESIGN-convert.md):
- in-place (default): reuse the existing `.git` (offline; keeps branches,
  stashes, config and — via auto-stash — uncommitted work).
- `--into <dir>`: build a fresh grove repo from the local objects, leaving the
  source clone untouched.

Submodules / Git LFS are blocked unless `force=True`.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from . import config
from .errors import UsageError, ValidationError
from .gitrunner import GitRunner
from .repo import RepoContext, write_git_pointer

Step = lambda m: None  # noqa: E731


def _detect_default_branch(git: GitRunner, gitdir: Path) -> Optional[str]:
    r = git.run(["symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"],
                cwd=gitdir, check=False, mutating=False)
    out = r.stdout.strip()
    if r.returncode == 0 and out.startswith("origin/"):
        return out.split("/", 1)[1]
    return None


def _all_branches(git: GitRunner, gitdir: Path) -> List[str]:
    out = git.out(["for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd=gitdir)
    return [b for b in out.splitlines()
            if b.strip() and b.strip() != config.PARKING_BRANCH]


def _branch_set(mode: str, cur: str, base: str, all_branches: List[str]) -> List[str]:
    if mode == "current":
        sel = [cur]
    elif mode == "all":
        sel = list(all_branches)
    else:  # current+base
        sel = [cur] + ([base] if base and base != cur else [])
    # de-dup preserving order
    seen, out = set(), []
    for b in sel:
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _has_lfs(path: Path, gitdir: Path) -> bool:
    if (gitdir / "lfs").exists():
        return True
    ga = path / ".gitattributes"
    try:
        return ga.is_file() and "filter=lfs" in ga.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def _preflight(git: GitRunner, src: Path, force: bool):
    """Validate the source and return (current_branch, base, origin_url)."""
    if not (src / ".git").exists():
        raise UsageError(f"{src} is not a git repository.")
    if (src / ".bare").exists():
        raise UsageError(f"{src} already looks like a grove repo (.bare/ exists).")
    if git.out(["rev-parse", "--is-bare-repository"], cwd=src) == "true":
        raise UsageError("Source is a bare repository; nothing to convert.")

    cur = git.run(["symbolic-ref", "--short", "-q", "HEAD"], cwd=src,
                  check=False, mutating=False).stdout.strip()
    if not cur:
        raise UsageError("Detached HEAD; check out a branch before converting.")

    gd = src / ".git"
    if (gd / "MERGE_HEAD").exists() or (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():
        raise UsageError("A merge/rebase is in progress; finish it before converting.")

    problems = []
    if (src / ".gitmodules").is_file():
        problems.append("submodules (.gitmodules)")
    if _has_lfs(src, gd):
        problems.append("Git LFS")
    if problems and not force:
        raise ValidationError(
            "Detected " + " and ".join(problems) + ". Conversion is blocked for "
            "safety (worktrees + submodules/LFS need extra handling). Re-run with "
            "--force to proceed anyway, or use --into to build beside the source."
        )

    detected = _detect_default_branch(git, src)
    base = detected or config.DEFAULT_BASE
    if not git.ok(["rev-parse", "--verify", f"refs/heads/{base}"], cwd=src):
        base = cur  # base not present locally → just use the current branch
    origin_url = git.run(["config", "--get", "remote.origin.url"], cwd=src,
                         check=False, mutating=False).stdout.strip() or None
    return cur, base, origin_url


def _wire_origin(git: GitRunner, bare: Path, origin_url: Optional[str], fetch: bool, step):
    if origin_url:
        git.run(["config", "remote.origin.fetch", config.ORIGIN_REFSPEC], cwd=bare, check=False)
    git.run(["config", "push.default", "current"], cwd=bare, check=False)
    if fetch and origin_url:
        step("Fetching origin")
        git.run(["fetch", "origin"], cwd=bare, check=False)


def _make_worktrees(git: GitRunner, bare: Path, root: Path, wts: List[str], origin_url, step):
    for b in wts:
        wp = root / b
        step(f"Creating worktree {b}/")
        git.run(["worktree", "add", str(wp), b], cwd=bare)
        if origin_url and git.ok(["rev-parse", "--verify", f"refs/remotes/origin/{b}"], cwd=bare):
            git.run(["branch", f"--set-upstream-to=origin/{b}", b], cwd=wp, check=False)


def convert(
    git: GitRunner,
    *,
    path: Path,
    into: Optional[Path] = None,
    branches: str = "current+base",
    fetch: bool = True,
    force: bool = False,
    git_pointer: bool = True,
    keep_on_error: bool = False,
    dry_run: bool = False,
    step: Step = lambda m: None,
) -> RepoContext:
    src = Path(path).resolve()
    cur, base, origin_url = _preflight(git, src, force)

    if dry_run:
        wts = _branch_set(branches, cur, base, _all_branches(git, src / ".git"))
        mode = f"--into {into}" if into else "in-place"
        step(f"[dry-run] mode: {mode}")
        step(f"[dry-run] base branch: {base}")
        step(f"[dry-run] worktrees to create: {', '.join(wts)}")
        step("[dry-run] no changes made")
        root = Path(into).resolve() if into else src
        return RepoContext(root=root, bare=root / ".bare", name=root.name, base=base)

    if into is not None:
        return _convert_into(git, src, Path(into).resolve(), cur, base, origin_url,
                             branches, fetch, git_pointer, keep_on_error, step)
    return _convert_in_place(git, src, cur, base, origin_url, branches, fetch,
                             git_pointer, keep_on_error, step)


def _convert_in_place(git, root, cur, base, origin_url, branches, fetch, git_pointer,
                      keep_on_error, step) -> RepoContext:
    bare = root / ".bare"

    # 1) Save uncommitted work (tracked + untracked) so nothing is lost.
    stashed = False
    if git.out(["status", "--porcelain"], cwd=root):
        step("Stashing uncommitted changes (git stash -u)")
        git.run(["stash", "push", "-u", "-m", "grove-convert"], cwd=root)
        stashed = True

    # Up to (and including) the stash, nothing destructive has happened. If the
    # pre-rename inspection fails, restore the stash and leave the repo intact.
    try:
        # Names to preserve (ignored) vs safe-to-drop (tracked) at the root.
        ignored_top = set()
        raw = git.run(["ls-files", "-o", "-i", "--exclude-standard", "--directory"],
                      cwd=root, check=False, mutating=False).stdout.splitlines()
        for e in raw:
            e = e.strip().strip("/")
            if e:
                ignored_top.add(e.split("/", 1)[0])
        tracked_top = {t.split("/", 1)[0] for t in
                       git.out(["ls-tree", "--name-only", f"refs/heads/{cur}"], cwd=root).splitlines()
                       if t.strip()}
    except BaseException:
        if not keep_on_error and stashed and (root / ".git").is_dir():
            step("Convert failed before any change — restoring stashed work")
            git.run(["stash", "pop"], cwd=root, check=False)
        raise

    # 2) Turn the repo bare: move .git -> .bare. From here the repo is being
    #    transformed in place; we do NOT auto-delete (it could discard files
    #    already moved into a worktree). On failure we report and stop so the
    #    user can inspect; `gwt doctor` and `git worktree list` help recover.
    step("Converting .git → .bare")
    (root / ".git").rename(bare)
    git.run(["config", "core.bare", "true"], cwd=bare)
    git.run(["worktree", "prune"], cwd=bare, check=False)
    _wire_origin(git, bare, origin_url, fetch, step)

    # 3) Parking branch + HEAD.
    if not git.ok(["rev-parse", "--verify", f"refs/heads/{config.PARKING_BRANCH}"], cwd=bare):
        git.run(["branch", config.PARKING_BRANCH, base], cwd=bare)
    git.run(["symbolic-ref", "HEAD", f"refs/heads/{config.PARKING_BRANCH}"], cwd=bare)

    # 4) Worktrees.
    wts = _branch_set(branches, cur, base, _all_branches(git, bare))
    _make_worktrees(git, bare, root, wts, origin_url, step)
    worktree_top = {b.split("/", 1)[0] for b in wts}

    # 5) Clean the orphaned root checkout: move ignored entries into the current
    #    worktree (preserve), drop tracked duplicates (safe — they're in git),
    #    and move anything unexpected into the worktree rather than deleting it.
    cur_wt = root / cur
    for entry in list(root.iterdir()):
        nm = entry.name
        if nm == ".bare" or nm in worktree_top:
            continue
        dest = cur_wt / nm
        if nm in ignored_top or nm not in tracked_top:
            if not dest.exists():
                shutil.move(str(entry), str(dest))
        else:  # tracked duplicate, reproduced in the worktree
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    # 6) Restore stashed work in the current worktree.
    if stashed:
        step(f"Restoring stashed changes in {cur}/")
        git.run(["stash", "pop"], cwd=cur_wt, check=False)

    if config.ARTIFACTS_DIR:
        (root / config.ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)
    if git_pointer and write_git_pointer(root):
        step("Writing root .git pointer (gitdir: ./.bare)")

    return RepoContext(root=root, bare=bare, name=root.name, base=base)


def _convert_into(git, src, dest, cur, base, origin_url, branches, fetch, git_pointer,
                  keep_on_error, step) -> RepoContext:
    if dest.exists() and any(dest.iterdir()):
        raise UsageError(f"--into target exists and is not empty: {dest}")
    preexisted = dest.exists()
    bare = dest / ".bare"
    dest.mkdir(parents=True, exist_ok=True)
    # The source is never touched, so cleanup here is safe: remove the new dir
    # (or, if it existed empty, just our contents) so a retry starts clean.
    try:
        return _convert_into_inner(git, src, dest, bare, cur, base, origin_url,
                                   branches, fetch, git_pointer, step)
    except BaseException:
        if not keep_on_error:
            step("Convert (--into) failed — cleaning up partial target")
            if not preexisted:
                shutil.rmtree(dest, ignore_errors=True)
            elif dest.is_dir():
                for child in dest.iterdir():
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        try:
                            child.unlink()
                        except OSError:
                            pass
        raise


def _convert_into_inner(git, src, dest, bare, cur, base, origin_url, branches, fetch,
                        git_pointer, step) -> RepoContext:
    step(f"Cloning local repo (bare) into {dest.name}/.bare")
    git.run(["clone", "--bare", str(src), str(bare)], cwd=None)
    if origin_url:
        git.run(["remote", "set-url", "origin", origin_url], cwd=bare, check=False)
    else:
        git.run(["remote", "remove", "origin"], cwd=bare, check=False)
    _wire_origin(git, bare, origin_url, fetch, step)

    if not git.ok(["rev-parse", "--verify", f"refs/heads/{config.PARKING_BRANCH}"], cwd=bare):
        git.run(["branch", config.PARKING_BRANCH, base], cwd=bare)
    git.run(["symbolic-ref", "HEAD", f"refs/heads/{config.PARKING_BRANCH}"], cwd=bare)

    wts = _branch_set(branches, cur, base, _all_branches(git, bare))
    _make_worktrees(git, bare, dest, wts, origin_url, step)

    if config.ARTIFACTS_DIR:
        (dest / config.ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)
    if git_pointer and write_git_pointer(dest):
        step("Writing root .git pointer (gitdir: ./.bare)")

    return RepoContext(root=dest, bare=bare, name=dest.name, base=base)
