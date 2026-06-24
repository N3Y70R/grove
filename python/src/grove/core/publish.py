"""Publish operation: brings ticket branches into the shared integration branch.

Two modes:
- additive: syncs the integration branch, merges the given branches and pushes.
- regenerate: resets the integration branch to the base, merges the branches and force-pushes.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from . import config, naming, ops
from .errors import GitError, ValidationError
from .gitrunner import GitRunner
from .model import list_worktrees
from .repo import RepoContext

Step = lambda m: None  # noqa: E731


def _local_branches(git: GitRunner, repo: RepoContext) -> List[str]:
    out = git.out(["for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd=repo.bare)
    return [b for b in out.splitlines() if b.strip()]


def resolve_branch(git: GitRunner, repo: RepoContext, query: str) -> str:
    """Resolves a target (ticket or branch) to a local branch name."""
    branches = _local_branches(git, repo)
    if query in branches:
        return query
    qt = naming.extract_ticket(query)
    if qt:
        matches = [b for b in branches if naming.extract_ticket(b) == qt]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValidationError(
                f"'{query}' is ambiguous. Matches: {', '.join(matches)}. Use the branch name."
            )
    raise ValidationError(f"No local branch found for '{query}'.")


def ensure_integration(git: GitRunner, repo: RepoContext, name: str, *, step=Step) -> Path:
    """Returns the path of the integration branch worktree; creates it if missing."""
    for w in list_worktrees(git, repo, with_status=False):
        if not w.is_bare and w.branch == name:
            return w.path
    # Does not exist locally: fetch it from origin or create it from a local branch.
    if ops.origin_branch_exists(git, repo, name):
        step(f"Integration branch '{name}' was not local; fetching it from origin")
        return ops.bring(git, repo, origin_branch=name, local_branch=name, rel_path=name, step=step)
    if name in _local_branches(git, repo):
        path = repo.root / name
        step(f"Creating worktree for the local integration branch '{name}'")
        git.run(["worktree", "add", str(path), name], cwd=repo.bare)
        return path
    raise ValidationError(
        f"Integration branch '{name}' exists neither locally nor on origin."
    )


def _merge_all(git: GitRunner, int_path: Path, branches: List[str], step=Step) -> None:
    for b in branches:
        step(f"Merging {b}")
        r = git.run(["merge", "--no-edit", b], cwd=int_path, check=False)
        if r.returncode != 0:
            git.run(["merge", "--abort"], cwd=int_path, check=False)
            raise GitError(
                f"Conflict while merging '{b}'. The merge was aborted; resolve it manually and retry."
            )


def publish_additive(
    git: GitRunner, repo: RepoContext, int_name: str, int_path: Path,
    branches: List[str], *, no_sync: bool = False, step=Step,
) -> None:
    if not no_sync:
        step(f"Syncing {int_name} with origin")
        git.run(["fetch", "origin", int_name], cwd=repo.bare)
        git.run(["reset", "--hard", f"origin/{int_name}"], cwd=int_path)
    _merge_all(git, int_path, branches, step=step)
    step(f"Push a origin/{int_name}")
    git.run(["push", "origin", int_name], cwd=int_path)


def publish_regenerate(
    git: GitRunner, repo: RepoContext, int_name: str, int_path: Path,
    branches: List[str], *, base: str, step=Step,
) -> None:
    step(f"Regenerating {int_name} from origin/{base}")
    git.run(["fetch", "origin", base], cwd=repo.bare)
    git.run(["reset", "--hard", f"origin/{base}"], cwd=int_path)
    _merge_all(git, int_path, branches, step=step)
    step(f"Force-push a origin/{int_name}")
    git.run(["push", "--force", "origin", int_name], cwd=int_path)
