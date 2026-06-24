"""Compare operation (read-only): sync status between branches/worktrees."""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import naming
from .errors import ValidationError, WtError
from .gitrunner import GitRunner
from .model import list_worktrees
from .repo import RepoContext


def _resolve_ref(git: GitRunner, repo: RepoContext, token: str) -> Tuple[str, str]:
    """Resolves a token to (ref, label). Worktree (by ticket/branch/path) or git ref."""
    from . import remove as core_remove
    try:
        wt = core_remove.resolve_target(git, repo, token)
        ref = wt.branch or wt.head
        if not ref:
            raise ValidationError(f"'{token}' has no comparable branch or HEAD.")
        return ref, wt.rel_path
    except WtError:
        if git.ok(["rev-parse", "--verify", token], cwd=repo.bare):
            return token, token
        raise ValidationError(f"'{token}' is neither a worktree nor a valid git ref.")


def _upstream_of(git: GitRunner, repo: RepoContext, ref: str) -> Optional[str]:
    res = git.run(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{ref}@{{upstream}}"],
        cwd=repo.bare, check=False, mutating=False,
    )
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else None


def ahead_behind(git: GitRunner, repo: RepoContext, a: str, b: str) -> Tuple[int, int]:
    """Returns (ahead, behind): commits in a not in b, and in b not in a."""
    out = git.out(["rev-list", "--left-right", "--count", f"{a}...{b}"], cwd=repo.bare)
    parts = out.split()
    if len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])


def status_word(ahead: int, behind: int) -> str:
    if ahead == 0 and behind == 0:
        return "in sync"
    if behind == 0:
        return "ahead"
    if ahead == 0:
        return "behind"
    return "diverged"


def compare_one(
    git: GitRunner, repo: RepoContext, a_token: Optional[str], b_token: Optional[str],
    *, cwd_branch: Optional[str] = None,
) -> dict:
    # Side A: explicit token, or the current worktree (cwd_branch).
    if a_token:
        a_ref, a_label = _resolve_ref(git, repo, a_token)
    elif cwd_branch:
        a_ref, a_label = cwd_branch, cwd_branch
    else:
        raise ValidationError(
            "The current worktree was not detected. Specify the worktree/branch to compare."
        )

    # Side B: explicit token, or the upstream of A.
    if b_token:
        b_ref, b_label = _resolve_ref(git, repo, b_token)
    else:
        up = _upstream_of(git, repo, a_ref)
        if not up:
            raise ValidationError(
                f"'{a_label}' has no upstream; specify what to compare against "
                f"(e.g. gwt compare {a_label} main)."
            )
        b_ref, b_label = up, up

    ahead, behind = ahead_behind(git, repo, a_ref, b_ref)
    return {"a": a_label, "b": b_label, "ahead": ahead, "behind": behind,
            "status": status_word(ahead, behind)}


def compare_all_vs(git: GitRunner, repo: RepoContext, ref_token: str) -> Tuple[str, List[dict]]:
    ref, ref_label = _resolve_ref(git, repo, ref_token)
    rows: List[dict] = []
    for w in list_worktrees(git, repo, with_status=False):
        if w.is_bare or not w.branch:
            continue
        ahead, behind = ahead_behind(git, repo, w.branch, ref)
        rows.append({"a": w.rel_path, "b": ref_label, "ahead": ahead, "behind": behind,
                     "status": status_word(ahead, behind)})
    return ref_label, rows
