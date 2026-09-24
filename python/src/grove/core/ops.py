"""Shared helpers for creating worktrees (used by create and track)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Callable

from . import config
from .errors import GitError, ValidationError
from .gitrunner import GitRunner
from .repo import RepoContext

Step = Callable[[str], None]


def _local_branch_exists(git: GitRunner, repo: RepoContext, branch: str) -> bool:
    return git.ok(["rev-parse", "--verify", f"refs/heads/{branch}"], cwd=repo.bare)


def origin_branch_exists(git: GitRunner, repo: RepoContext, branch: str) -> bool:
    return git.ok(["rev-parse", "--verify", f"refs/remotes/origin/{branch}"], cwd=repo.bare)


def _ensure_free(repo: RepoContext, rel_path: str) -> Path:
    path = repo.root / Path(rel_path)
    if path.exists():
        raise ValidationError(f"The destination folder already exists: {rel_path}")
    return path


# Usual names for a base branch, tried when the requested one doesn't exist.
_COMMON_BASES = ("main", "master", "production", "develop", "development")


def branch_candidates(git: GitRunner, cwd, prefixes=("refs/heads/", "refs/remotes/origin/"),
                      exclude=()) -> List[str]:
    """Existing branches worth suggesting as a base: the configured base and the
    usual names first; if none exists, whatever branches there are (max 8)."""
    def exists(name):
        return any(git.ok(["rev-parse", "--verify", "-q", f"{p}{name}"], cwd=cwd) for p in prefixes)

    wanted = [config.DEFAULT_BASE, *_COMMON_BASES]
    found = [b for i, b in enumerate(wanted) if b not in wanted[:i] and b not in exclude and exists(b)]
    if found:
        return found
    names = []
    for p in prefixes:
        out = git.run(["for-each-ref", "--format=%(refname)", p], cwd=cwd,
                      check=False, mutating=False).stdout.split()
        for ref in out:
            n = ref[len(p):]
            if n not in names and n not in exclude and n not in ("HEAD", config.PARKING_BRANCH):
                names.append(n)
    return names[:8]


def _require_base(git: GitRunner, repo: RepoContext, base: str) -> None:
    """Fail with a helpful message (instead of git's 'invalid reference') when
    the base doesn't exist locally or on origin."""
    if git.ok(["rev-parse", "--verify", "-q", f"{base}^{{commit}}"], cwd=repo.bare):
        return
    if git.ok(["rev-parse", "--verify", "-q", f"refs/remotes/origin/{base}"], cwd=repo.bare):
        return
    cands = branch_candidates(git, repo.bare, exclude=(base,))
    msg = f"Base branch '{base}' does not exist (locally or on origin)."
    if cands:
        msg += f" Existing candidates: {', '.join(cands)}."
        if base == config.DEFAULT_BASE:
            msg += (f" The repo's default_base looks outdated; fix it with: "
                    f"gwt config set default_base {cands[0]}")
        else:
            msg += f" Use --base {cands[0]}."
    raise ValidationError(msg)


def add_new(
    git: GitRunner,
    repo: RepoContext,
    *,
    branch: str,
    rel_path: str,
    base: str,
    step: Step = lambda m: None,
) -> Path:
    """Creates a NEW branch from 'base' and its worktree. No upstream (set on push)."""
    if _local_branch_exists(git, repo, branch) or origin_branch_exists(git, repo, branch):
        raise ValidationError(
            f"Branch '{branch}' already exists. "
            f"Use 'gwt track {branch}' to create the worktree from the existing branch."
        )
    _require_base(git, repo, base)
    path = _ensure_free(repo, rel_path)
    step(f"Creating worktree {rel_path}/ with new branch {branch} (base {base})")
    # --no-track: a new branch must not adopt its base as upstream (git would do
    # so when the base is a remote-tracking ref such as origin/main); the upstream
    # is set on the first `git push -u`.
    git.run(["worktree", "add", "--no-track", "-b", branch, str(path), base], cwd=repo.bare)
    return path


def add_existing_local(
    git: GitRunner,
    repo: RepoContext,
    *,
    local_branch: str,
    rel_path: str,
    from_ref: str = None,  # type: ignore[assignment]
    step: Step = lambda m: None,
) -> Path:
    """Creates a worktree for a LOCAL branch that already exists (without origin upstream).

    If local_branch does not exist and from_ref is given, creates local_branch from from_ref.
    """
    path = _ensure_free(repo, rel_path)
    if _local_branch_exists(git, repo, local_branch):
        step(f"Creating worktree {rel_path}/ (local branch {local_branch})")
        git.run(["worktree", "add", str(path), local_branch], cwd=repo.bare)
    elif from_ref:
        step(f"Creating worktree {rel_path}/ with branch {local_branch} (from {from_ref})")
        git.run(["worktree", "add", "-b", local_branch, str(path), from_ref], cwd=repo.bare)
    else:
        raise ValidationError(f"The local branch '{local_branch}' does not exist.")
    return path


def bring(
    git: GitRunner,
    repo: RepoContext,
    *,
    origin_branch: str,
    local_branch: str,
    rel_path: str,
    step: Step = lambda m: None,
) -> Path:
    """Brings an EXISTING origin branch as a worktree and sets/verifies the upstream."""
    if not origin_branch_exists(git, repo, origin_branch):
        raise ValidationError(f"The branch 'origin/{origin_branch}' does not exist on origin.")
    path = _ensure_free(repo, rel_path)
    origin_ref = f"origin/{origin_branch}"

    if _local_branch_exists(git, repo, local_branch):
        step(f"Creating worktree {rel_path}/ (local branch {local_branch})")
        git.run(["worktree", "add", str(path), local_branch], cwd=repo.bare)
    else:
        step(f"Creating worktree {rel_path}/ tracking {origin_ref}")
        git.run(["worktree", "add", "--track", "-b", local_branch, str(path), origin_ref],
                cwd=repo.bare)

    step(f"Setting upstream {local_branch} -> {origin_ref}")
    git.run(["branch", f"--set-upstream-to={origin_ref}", local_branch], cwd=path)

    # Post-creation verification.
    actual = git.out(["rev-parse", "--abbrev-ref", f"{local_branch}@{{upstream}}"], cwd=path)
    if actual != origin_ref:
        raise GitError(
            f"Upstream verification failed: expected {origin_ref} but got '{actual}'."
        )
    step("Verifying upstream ✓")
    return path
