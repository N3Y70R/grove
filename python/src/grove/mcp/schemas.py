"""Typed output schemas for the MCP tools.

Each tool that returns a stable shape declares it here, so its MCP output
schema lists every field with its type and a description, and an agent knows
beforehand what it will receive. Keep them in sync with `_ops`:
`tests/test_mcp_output_contract.py` calls every typed tool and fails if a key
is missing or undeclared — the SDK silently drops undeclared keys from
`structured_content` and errors on a missing required one.

`typing_extensions.TypedDict` (not `typing`): pydantic needs it on Python < 3.12.
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import Field
from typing_extensions import NotRequired, TypedDict

Status = Literal["in sync", "ahead", "behind", "diverged"]
Kind = Literal["base", "special", "temp", "ticket", "release", "unknown"]


def D(text: str):
    return Field(description=text)


# --------------------------------------------------------------------------- #
# Repository
# --------------------------------------------------------------------------- #

class SetupResult(TypedDict):
    name: Annotated[str, D("Repo folder name.")]
    root: Annotated[str, D("Absolute path of the new managed repo.")]
    profile: Annotated[str, D("Policy profile applied and recorded in grove.toml.")]
    base: Annotated[str, D("Base branch in use (may be auto-detected from origin).")]


class ConvertResult(TypedDict):
    name: Annotated[str, D("Repo folder name.")]
    root: Annotated[str, D("Absolute path of the converted (or new, with into) repo.")]
    base: Annotated[str, D("Base branch detected for the repo.")]
    profile: Annotated[str, D("Policy profile applied and recorded in grove.toml.")]
    into: Annotated[bool, D("True when a new repo was built beside the source (source untouched).")]
    dry_run: Annotated[bool, D("True when nothing was changed (plan only).")]


# --------------------------------------------------------------------------- #
# Worktrees
# --------------------------------------------------------------------------- #

class WorktreeRow(TypedDict):
    path: Annotated[str, D("Absolute path of the worktree (local to this machine).")]
    rel_path: Annotated[str, D("Folder relative to the repo root; equals the branch name by convention.")]
    branch: Annotated[Optional[str], D("Branch checked out; null for the bare entry or a detached HEAD.")]
    bare: Annotated[bool, D("True for the .bare entry (the repository itself, not a worktree).")]
    detached: Annotated[bool, D("True when the worktree is in detached HEAD.")]
    prunable: Annotated[bool, D("True when git considers the record orphaned (no folder on disk).")]
    exists: Annotated[bool, D("True when the worktree folder exists.")]
    ticket: Annotated[Optional[str], D("Ticket key parsed from the name (e.g. PROJ-123), or null.")]
    kind: Annotated[Optional[Kind], D("Classification: base, special, temp, ticket, release or unknown; null for bare.")]
    type: Annotated[Optional[str], D("Ticket type folder (feature/hotfix/bugfix…) or 'release'; null otherwise.")]
    dirty: Annotated[Optional[bool], D("Uncommitted changes; null when not computed.")]
    ahead: Annotated[Optional[int], D("Commits ahead of compared_to; null when not computed.")]
    behind: Annotated[Optional[int], D("Commits behind compared_to; null when not computed.")]
    upstream: Annotated[Optional[str], D("Upstream branch (e.g. origin/main), or null if none.")]
    gitdir: Annotated[Optional[str], D("Internal admin dir relative to the repo root (e.g. .bare/worktrees/X): use as GIT_DIR from another mount.")]
    merged: Annotated[Optional[bool], D("True when the branch has no commits outside the base (what remove merged=true would sweep); null for the base.")]
    compared_to: Annotated[Optional[str], D("What ahead/behind are measured against: the upstream, or the base when there is no upstream.")]


class ListResult(TypedDict):
    count: Annotated[int, D("Number of rows returned (after filters).")]
    worktrees: Annotated[List[WorktreeRow], D("One row per worktree, plus the bare entry.")]


class CreateResult(TypedDict):
    path: Annotated[str, D("Absolute path of the new worktree.")]
    rel_path: Annotated[str, D("Folder relative to the repo root.")]
    branch: Annotated[str, D("Branch created (equals rel_path for ticket/temp worktrees).")]


class TrackResult(CreateResult):
    warnings: Annotated[List[str], D("Non-fatal notices (e.g. a type not in allowed_types).")]


class StartResult(TypedDict):
    mode: Annotated[Literal["existing", "resumed", "created"], D("existing: worktree already there; resumed: existing branch brought in; created: new branch from the base.")]
    path: Annotated[str, D("Absolute path of the worktree to work in.")]
    rel_path: Annotated[str, D("Folder relative to the repo root.")]
    branch: Annotated[str, D("Branch of the worktree.")]
    base: Annotated[Optional[str], D("Start point used when created (e.g. origin/main); null otherwise.")]
    ticket: Annotated[Optional[str], D("Ticket key parsed from the branch, or null.")]
    upstream: Annotated[Optional[str], D("Upstream branch, or null (a new branch gets it on the first git push -u).")]
    gitdir: Annotated[Optional[str], D("Internal admin dir relative to the repo root.")]
    next_steps: Annotated[List[str], D("Shell commands to run next (cd, first push…).")]


class RemoveResult(TypedDict):
    mode: Annotated[Literal["single", "merged"], D("single: one target; merged: sweep of merged ticket worktrees.")]
    removed: Annotated[List[str], D("Worktrees removed — or that WOULD be removed when dry_run is true.")]
    dry_run: Annotated[bool, D("True when nothing was changed (preview).")]
    delete_branch: NotRequired[Annotated[bool, D("Whether the local branch was also deleted (single mode).")]]


# --------------------------------------------------------------------------- #
# Remote
# --------------------------------------------------------------------------- #

class ResetResult(TypedDict):
    worktree: Annotated[str, D("Worktree reset (folder relative to the repo root).")]
    upstream: Annotated[str, D("Origin branch it was reset to (e.g. origin/main).")]
    discarded: Annotated[List[str], D("What was discarded (unpushed commits, uncommitted changes); empty if nothing.")]
    deprecated: NotRequired[Annotated[str, D("Present only when called through the deprecated grove_sync.")]]


class FetchRow(TypedDict):
    worktree: Annotated[str, D("Folder relative to the repo root.")]
    branch: Annotated[Optional[str], D("Branch checked out, or null.")]
    compared_to: Annotated[Optional[str], D("Upstream, or the base when there is no upstream.")]
    ahead: Annotated[Optional[int], D("Commits ahead of compared_to.")]
    behind: Annotated[Optional[int], D("Commits behind compared_to (> 0: there is something to bring in).")]
    status: Annotated[Optional[Status], D("in sync / ahead / behind / diverged; null when not computable.")]
    dirty: Annotated[Optional[bool], D("Uncommitted changes.")]


class FetchResult(TypedDict):
    prune: Annotated[bool, D("Whether origin/* refs of branches deleted on the remote were dropped.")]
    worktrees: Annotated[List[FetchRow], D("Where each worktree stands after the fetch (worktrees are never modified).")]


class CompareRow(TypedDict):
    a: Annotated[str, D("Worktree or branch compared.")]
    b: Annotated[str, D("What it was compared against.")]
    ahead: Annotated[int, D("Commits in a that b doesn't have.")]
    behind: Annotated[int, D("Commits in b that a doesn't have.")]
    status: Annotated[Status, D("in sync / ahead / behind / diverged.")]


class CompareResult(TypedDict):
    """One comparison (a, b, ahead, behind, status) — or, with vs, all worktrees (vs, rows)."""
    a: NotRequired[Annotated[str, D("Single comparison: worktree or branch compared.")]]
    b: NotRequired[Annotated[str, D("Single comparison: what it was compared against.")]]
    ahead: NotRequired[Annotated[int, D("Single comparison: commits in a that b doesn't have.")]]
    behind: NotRequired[Annotated[int, D("Single comparison: commits in b that a doesn't have.")]]
    status: NotRequired[Annotated[Status, D("Single comparison: in sync / ahead / behind / diverged.")]]
    vs: NotRequired[Annotated[str, D("With vs: the ref every worktree was compared against.")]]
    rows: NotRequired[Annotated[List[CompareRow], D("With vs: one row per worktree.")]]


# --------------------------------------------------------------------------- #
# Maintenance
# --------------------------------------------------------------------------- #

class DoctorIssue(TypedDict):
    kind: Annotated[str, D("Problem type, e.g. orphan, upstream, naming, stale-lock, lock, stale-tmp, identity, bare-head, parking-branch, worktree-paths.")]
    severity: Annotated[Literal["auto", "manual"], D("auto: fixable with fix=true; manual: needs human judgment.")]
    target: Annotated[str, D("Affected worktree, branch or file.")]
    message: Annotated[str, D("What is wrong.")]
    action: Annotated[str, D("What the fix does (auto) or what to do (manual).")]
    fixable: Annotated[bool, D("True when fix=true would repair it.")]


class DoctorResult(TypedDict):
    issues: Annotated[List[DoctorIssue], D("Problems found (empty when healthy).")]
    auto_fixable: Annotated[int, D("How many issues fix=true can repair.")]
    manual: Annotated[int, D("How many need manual review.")]
    applied: Annotated[int, D("Fixes applied in this call (0 unless fix=true).")]
    version: Annotated[str, D("grove version that produced this report.")]
