"""Track operation: brings an existing branch (local or from origin) into the structure.

`track` *accommodates* what already exists, which is why it is more permissive than `create`:
it accepts local branches in addition to origin, and brings branches whose type is not in
`allowed_types` (with a warning), because `allowed_types` only restricts what is *created*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import config, naming, ops
from .errors import ValidationError
from .gitrunner import GitRunner
from .repo import RepoContext

Step = ops.Step


def _is_parseable(branch: str) -> bool:
    """Does the branch have a placeable form in the structure? (does not require an allowed type)."""
    if branch in config.SPECIAL_WORKTREES:
        return True
    head = branch.split("/", 1)[0]
    if head == config.TEMP_DIR:
        return True
    # Any <segment>/<non-empty-rest> is placeable (feature/.., chore/.., release/..).
    if "/" in branch and branch.split("/", 1)[1].strip():
        return True
    return False


def _known_segment(head: str) -> bool:
    return (
        head in config.TICKET_TYPES
        or head == config.RELEASE_TYPE
        or head == config.TEMP_DIR
        or head in config.SPECIAL_WORKTREES
    )


def track(
    git: GitRunner,
    repo: RepoContext,
    *,
    branch: str,
    as_: Optional[str] = None,
    step: Step = lambda m: None,
    warn: Step = lambda m: None,
) -> Path:
    origin_exists = ops.origin_branch_exists(git, repo, branch)
    local_exists = ops._local_branch_exists(git, repo, branch)
    if not origin_exists and not local_exists:
        raise ValidationError(
            f"Branch '{branch}' exists neither locally nor on origin."
        )

    if as_:
        rel_path = as_.replace("\\", "/").strip("/")
        local_branch = rel_path
        step(f"Explicit destination (--as): {rel_path}")
    else:
        if not _is_parseable(branch):
            raise ValidationError(
                f"'{branch}' is not placeable in the structure (expected <type>/...).\n"
                f"  Specify the destination with --as, for example:\n"
                f"    gwt track {branch} --as hotfix/TICKET-XXXXX-description"
            )
        rel_path = branch
        local_branch = branch
        head = branch.split("/", 1)[0]
        if not _known_segment(head):
            # Type outside allowed_types: accommodated anyway, with a warning (not an error).
            warn(f"'{head}' is not in allowed_types; bringing the branch anyway "
                 f"(allowed_types only restricts 'create').")
        else:
            cls = naming.parse_origin_branch(branch)
            info = cls.ticket or cls.version or cls.kind
            step(f"Parsed: type={cls.type} · {info}")

    if origin_exists:
        return ops.bring(
            git, repo,
            origin_branch=branch, local_branch=local_branch, rel_path=rel_path, step=step,
        )
    # Local only: no origin upstream.
    return ops.add_existing_local(
        git, repo,
        local_branch=local_branch,
        rel_path=rel_path,
        from_ref=(branch if local_branch != branch else None),
        step=step,
    )
