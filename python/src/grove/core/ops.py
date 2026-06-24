"""Shared helpers for creating worktrees (used by create and track)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

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
    path = _ensure_free(repo, rel_path)
    step(f"Creating worktree {rel_path}/ with new branch {branch} (base {base})")
    git.run(["worktree", "add", "-b", branch, str(path), base], cwd=repo.bare)
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
    git.run([f"branch", f"--set-upstream-to={origin_ref}", local_branch], cwd=path)

    # Post-creation verification.
    actual = git.out(["rev-parse", "--abbrev-ref", f"{local_branch}@{{upstream}}"], cwd=path)
    if actual != origin_ref:
        raise GitError(
            f"Upstream verification failed: expected {origin_ref} but got '{actual}'."
        )
    step("Verifying upstream ✓")
    return path
