"""Start operation: one idempotent call to start — or resume — work on a ticket.

    1. fetch origin (unless disabled), so the base is current;
    2. a worktree for the ticket already exists  → return it   (mode "existing");
    3. a branch for the ticket exists (local or origin) but has no worktree
                                                 → track it    (mode "resumed");
    4. otherwise create it from origin/<base> (the freshly fetched base) or,
       when the base isn't on origin, from the local base  (mode "created").

grove never queries a ticket system: the key and name arrive by parameter.
"""

from __future__ import annotations

from typing import List, Optional

from . import config, create, naming, ops, track
from .errors import ValidationError
from .gitrunner import GitRunner
from .model import list_worktrees
from .repo import RepoContext

Step = ops.Step


def _branches(git: GitRunner, repo: RepoContext) -> List[str]:
    names: List[str] = []
    for prefix in ("refs/heads/", "refs/remotes/origin/"):
        out = git.run(["for-each-ref", "--format=%(refname)", prefix], cwd=repo.bare,
                      check=False, mutating=False).stdout.split()
        for ref in out:
            n = ref[len(prefix):]
            if n not in names and n not in ("HEAD", config.PARKING_BRANCH):
                names.append(n)
    return names


def _matches(branch: Optional[str], rel_path: str, ticket: Optional[str]) -> bool:
    if not branch:
        return False
    if branch == rel_path:
        return True
    return bool(ticket) and "/" in branch and naming.extract_ticket(branch) == ticket


def start(
    git: GitRunner,
    repo: RepoContext,
    *,
    type: str,
    name: str,
    ticket: Optional[str] = None,
    base: Optional[str] = None,
    fetch: bool = True,
    step: Step = lambda m: None,
    warn: Step = lambda m: None,
) -> dict:
    rel_path, norm_ticket, _ = create.plan_ticket(type=type, name=name, ticket=ticket)

    if fetch:
        step("Fetching from origin")
        git.run(["fetch", "origin"], cwd=repo.bare)

    # 2) existing worktree
    wts = [w for w in list_worktrees(git, repo, with_status=False) if not w.is_bare]
    found = [w for w in wts if _matches(w.branch, rel_path, norm_ticket)]
    if len(found) > 1:
        raise ValidationError(
            f"Several worktrees match {norm_ticket or rel_path}: "
            f"{', '.join(w.rel_path for w in found)}. Use the exact branch.")
    if found:
        step(f"Worktree already exists: {found[0].rel_path}")
        return _result(git, repo, "existing", found[0].branch, base=None)

    # 3) existing branch without worktree
    cands = [b for b in _branches(git, repo) if _matches(b, rel_path, norm_ticket)]
    if len(cands) > 1:
        raise ValidationError(
            f"Several branches match {norm_ticket or rel_path}: {', '.join(sorted(cands))}. "
            f"Resume one with 'gwt track <branch>'.")
    if cands:
        step(f"Resuming existing branch {cands[0]}")
        track.track(git, repo, branch=cands[0], step=step, warn=warn)
        return _result(git, repo, "resumed", cands[0], base=None)

    # 4) create from the freshly fetched base
    base = base or config.DEFAULT_BASE
    start_point = base
    if not base.startswith("origin/") and ops.origin_branch_exists(git, repo, base):
        start_point = f"origin/{base}"
    create.create_ticket(git, repo, type=type, name=name, ticket=ticket,
                         base=start_point, step=step)
    return _result(git, repo, "created", rel_path, base=start_point)


def _result(git: GitRunner, repo: RepoContext, mode: str, branch: str,
            base: Optional[str]) -> dict:
    wt = next(w for w in list_worktrees(git, repo, with_status=True) if w.branch == branch)
    steps = [f"cd {wt.path}"]
    if not wt.upstream:
        steps.append(f"git push -u origin {branch}   # first push creates the branch on origin")
    return {
        "mode": mode,
        "path": str(wt.path),
        "rel_path": wt.rel_path,
        "branch": branch,
        "base": base,
        "ticket": naming.extract_ticket(branch),
        "upstream": wt.upstream,
        "gitdir": wt.gitdir,
        "next_steps": steps,
    }
