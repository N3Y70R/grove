"""Remove operation: safely removes worktrees (individual or bulk)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import config, naming
from .errors import ValidationError
from .gitrunner import GitRunner
from .model import Worktree, list_worktrees
from .repo import RepoContext

Step = lambda m: None  # noqa: E731  (placeholder; replaced by the real callback)


def _is_special(wt: Worktree) -> bool:
    return bool(wt.classification and wt.classification.kind == "special")


def resolve_target(git: GitRunner, repo: RepoContext, query: str) -> Worktree:
    """Finds the worktree that matches query (ticket | branch | path)."""
    wts = [w for w in list_worktrees(git, repo, with_status=True) if not w.is_bare]
    q = query.replace("\\", "/").strip("/")
    qticket = naming.extract_ticket(query)

    matches: List[Worktree] = []
    for w in wts:
        if w.rel_path == q or w.branch == q:
            return w  # exact path or branch match: unambiguous
        if qticket and naming.extract_ticket(w.rel_path) == qticket:
            matches.append(w)
        elif Path(w.rel_path).name == q:
            matches.append(w)

    if not matches:
        raise ValidationError(f"No worktree found for '{query}'.")
    if len(matches) > 1:
        opciones = ", ".join(m.rel_path for m in matches)
        raise ValidationError(
            f"'{query}' is ambiguous. Matches: {opciones}. Specify the exact path or branch."
        )
    return matches[0]


def _branch_merged(git: GitRunner, repo: RepoContext, branch: str, base: str) -> bool:
    return git.ok(["merge-base", "--is-ancestor", branch, base], cwd=repo.bare)


def _branch_pushed(wt: Worktree) -> bool:
    # Pushed and with no local commits pending relative to upstream.
    return wt.upstream is not None and (wt.ahead in (0, None))


@dataclass
class RemovalPlan:
    wt: Worktree
    remove_worktree: bool = True
    delete_branch: bool = False
    notes: List[str] = None  # type: ignore


def remove_one(
    git: GitRunner,
    repo: RepoContext,
    wt: Worktree,
    *,
    delete_branch: bool = False,
    force: bool = False,
    base: Optional[str] = None,
    step=Step,
) -> None:
    if _is_special(wt):
        raise ValidationError(
            f"'{wt.rel_path}' is a protected special worktree; it is not removed with remove."
        )

    base = base or config.DEFAULT_BASE

    # Safety: uncommitted changes.
    if wt.dirty and not force:
        raise ValidationError(
            f"'{wt.rel_path}' has uncommitted changes. Use --force to remove it anyway."
        )

    # Decision about the branch.
    will_delete_branch = False
    if delete_branch and wt.branch:
        if force:
            will_delete_branch = True
        else:
            merged = _branch_merged(git, repo, wt.branch, base)
            pushed = _branch_pushed(wt)
            if merged or pushed:
                will_delete_branch = True
            else:
                raise ValidationError(
                    f"Branch '{wt.branch}' is neither merged into {base} nor pushed; "
                    f"it is not deleted. Use --force to delete it anyway."
                )

    # Execute (GitRunner respects dry_run: in that mode it does not mutate, only reports the steps).
    rm_args = ["worktree", "remove", str(wt.path)]
    if force:
        rm_args.append("--force")
    step(f"Removing worktree {wt.rel_path}")
    git.run(rm_args, cwd=repo.bare)

    if will_delete_branch:
        step(f"Deleting branch {wt.branch}")
        # -D deletes unconditionally; we already validated safety above.
        git.run(["branch", "-D", wt.branch], cwd=repo.bare)
    elif delete_branch:
        pass  # the condition was not met (it would have raised an error without --force)
    else:
        step(f"Branch {wt.branch} kept")


def sweep_merged(
    git: GitRunner,
    repo: RepoContext,
    *,
    delete_branch: bool = False,
    force: bool = False,
    base: Optional[str] = None,
    step=Step,
) -> List[Worktree]:
    """Removes all TICKET worktrees whose branch is merged into the base."""
    base = base or config.DEFAULT_BASE
    wts = [w for w in list_worktrees(git, repo, with_status=True) if not w.is_bare]
    removed: List[Worktree] = []
    for w in wts:
        if not (w.classification and w.classification.kind == "ticket"):
            continue
        if not w.branch or not w.exists:
            continue
        if w.branch == base:
            continue
        if _branch_merged(git, repo, w.branch, base):
            remove_one(git, repo, w, delete_branch=delete_branch, force=force, base=base, step=step)
            removed.append(w)
    return removed
