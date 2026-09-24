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

from typing import Annotated, Any, Dict, List, Literal, Optional

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
    kind: Annotated[str, D("Problem type, e.g. orphan, upstream, naming, stale-lock, lock, stale-tmp, identity, bare-head, parking-branch, worktree-paths, skill-outdated.")]
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


# --------------------------------------------------------------------------- #
# Configuration (one schema for the four modes: show / set / unset / ssh alias)
# --------------------------------------------------------------------------- #

class ReleasePolicy(TypedDict):
    format: Annotated[str, D("Release branch format, e.g. release/{version}.")]
    default_base: Annotated[str, D("Base for new release branches.")]


class ConfigResult(TypedDict):
    """Show: repo, root, origin, version and the effective policy. set_key: key,
    value, config (+ applied for relative_worktrees). unset_key: unset, config.
    set_ssh_alias: ssh_alias, origin."""
    repo: NotRequired[Annotated[str, D("show: repo name.")]]
    root: NotRequired[Annotated[str, D("show: absolute path of the managed repo.")]]
    origin: NotRequired[Annotated[Optional[str], D("show / set_ssh_alias: origin URL (after the rewrite, for set_ssh_alias).")]]
    version: NotRequired[Annotated[str, D("show: grove version.")]]
    profile: NotRequired[Annotated[Optional[str], D("show: policy profile the repo was created with.")]]
    default_base: NotRequired[Annotated[str, D("show: base branch for new worktrees.")]]
    allowed_types: NotRequired[Annotated[List[str], D("show: ticket types `create` accepts.")]]
    special_worktrees: NotRequired[Annotated[List[str], D("show: protected special worktrees.")]]
    temp_dir: NotRequired[Annotated[str, D("show: folder for temp worktrees.")]]
    artifacts_dir: NotRequired[Annotated[str, D("show: local, never-versioned artifacts folder ('' = disabled).")]]
    tickets: NotRequired[Annotated[Literal["required", "optional", "off"], D("show: ticket policy.")]]
    integration_branch: NotRequired[Annotated[str, D("show: shared integration branch for publish ('' = none).")]]
    ssh_alias: NotRequired[Annotated[str, D("show / set_ssh_alias: ~/.ssh/config alias for the remote ('' = none).")]]
    known_git_hosts: NotRequired[Annotated[List[str], D("show: hosts for `ssh check --all` without ~/.ssh/config.")]]
    relative_worktrees: NotRequired[Annotated[bool, D("show: whether worktrees use relative paths.")]]
    release: NotRequired[Annotated[ReleasePolicy, D("show: release branch policy.")]]
    ticket_prefixes: NotRequired[Annotated[List[str], D("show: accepted ticket keys (when configured).")]]
    ticket_pattern: NotRequired[Annotated[str, D("show: ticket regex (when no prefixes are configured).")]]
    key: NotRequired[Annotated[str, D("set_key: the key set.")]]
    value: NotRequired[Annotated[Any, D("set_key: the stored value (lists for list keys, booleans for boolean keys).")]]
    applied: NotRequired[Annotated[Optional[Literal["enable", "disable"]], D("set_key relative_worktrees: conversion performed, or null if none was needed.")]]
    unset: NotRequired[Annotated[str, D("unset_key: the key removed (falls back to the repo's profile).")]]
    config: NotRequired[Annotated[Dict[str, Any], D("set_key / unset_key: the resulting grove.toml contents.")]]


# --------------------------------------------------------------------------- #
# Publish
# --------------------------------------------------------------------------- #

class PublishResult(TypedDict):
    integration: Annotated[str, D("Integration branch published to.")]
    mode: Annotated[Literal["additive", "regenerate", "created"], D("additive: merged on top; regenerate: rebuilt from base (force-push); created: new from base.")]
    created: Annotated[bool, D("True when the integration branch did not exist and was created.")]
    branches: Annotated[List[str], D("Branches merged in, in order.")]
    base: Annotated[Optional[str], D("Base used for regenerate/creation, or null.")]


# --------------------------------------------------------------------------- #
# SSH
# --------------------------------------------------------------------------- #

class SshIdentity(TypedDict):
    path: Annotated[str, D("Private key path (IdentityFile).")]
    exists: Annotated[bool, D("Whether the key file exists.")]
    perms_ok: Annotated[Optional[bool], D("Key permissions are safe (600); null when not applicable (e.g. Windows).")]
    loaded: Annotated[Optional[bool], D("Key loaded in the ssh-agent; null when it can't be determined.")]


class SshLive(TypedDict):
    ok: Annotated[bool, D("Authentication succeeded (ssh -T).")]
    message: Annotated[str, D("Server's answer or the error.")]


class SshHost(TypedDict):
    target: Annotated[str, D("Host or alias diagnosed.")]
    hostname: Annotated[Optional[str], D("Resolved HostName.")]
    user: Annotated[Optional[str], D("Resolved User.")]
    identities_only: Annotated[Optional[bool], D("IdentitiesOnly setting (only the listed keys are offered).")]
    config_present: Annotated[bool, D("Whether ~/.ssh/config exists.")]
    identities: Annotated[List[SshIdentity], D("Keys that would be offered.")]
    agent_running: Annotated[bool, D("Whether an ssh-agent is reachable.")]
    agent_keys: Annotated[int, D("Number of keys loaded in the agent.")]
    live: Annotated[Optional[SshLive], D("Live authentication result (only with live=true).")]
    error: Annotated[Optional[str], D("Why the host couldn't be diagnosed, if so.")]


class SshCheckResult(TypedDict):
    hosts: Annotated[List[SshHost], D("One report per host diagnosed.")]


class SshAliasMatch(TypedDict):
    alias: Annotated[str, D("~/.ssh/config Host alias.")]
    hostname: Annotated[str, D("Real host the alias resolves to.")]
    identity_files: Annotated[List[str], D("Keys the alias offers.")]
    current: Annotated[bool, D("True for the alias the repo's origin uses now.")]


class SshAliasesResult(TypedDict):
    host: Annotated[str, D("Real host of the repo's origin (or of the target).")]
    current: Annotated[Optional[str], D("Alias currently in use, or null.")]
    aliases: Annotated[List[SshAliasMatch], D("Aliases that resolve to that host.")]


class SshAddResult(TypedDict):
    name: Annotated[str, D("Account alias.")]
    host: Annotated[str, D("Real host (e.g. github.com).")]
    key: Annotated[str, D("Private key path.")]
    created_key: Annotated[bool, D("True when a new key was generated (false when reused).")]
    pubkey: Annotated[Optional[str], D("Public key to upload to the host (grove never uploads it).")]
    zone: Annotated[Optional[str], D("Folder whose repos use this account (git identity routing), or null.")]
    email: Annotated[Optional[str], D("Git identity email for the zone, or null.")]
    name_missing: Annotated[bool, D("True when no global git user.name is set.")]
    dry_run: Annotated[bool, D("True when nothing was written (preview).")]
    steps: Annotated[List[str], D("What was done (or would be done).")]


class SshAccount(TypedDict):
    name: Annotated[str, D("Account alias.")]
    host: Annotated[str, D("Real host.")]
    key: Annotated[Optional[str], D("Private key path.")]
    zone: Annotated[Optional[str], D("Folder routed to this account, or null.")]
    email: Annotated[Optional[str], D("Git identity email of the zone, or null.")]
    routing: Annotated[Literal["ok", "partial", "none"], D("Coherence of the git identity routing.")]


class SshZone(TypedDict):
    scope_dir: Annotated[str, D("Folder of the zone.")]
    email: Annotated[Optional[str], D("Git identity email used inside it.")]
    identity_path: Annotated[str, D("grove-managed gitconfig file for the zone.")]
    rewrites: Annotated[Dict[str, str], D("URL rewrites host → alias applied inside the zone.")]


class SshAccountsResult(TypedDict):
    accounts: Annotated[List[SshAccount], D("grove-managed SSH accounts.")]
    zones: Annotated[List[SshZone], D("Folder zones with git identity routing.")]


class SshFinding(TypedDict):
    check: Annotated[str, D("Check that fired (e.g. trap, useconfigonly, perms, secret).")]
    severity: Annotated[Literal["fix", "review"], D("fix: auto-fixable with fix=true; review: manual.")]
    target: Annotated[str, D("Affected account, file or setting.")]
    message: Annotated[str, D("What is wrong.")]
    fixable: Annotated[bool, D("True when fix=true would repair it.")]


class SshDoctorResult(TypedDict):
    findings: Annotated[List[SshFinding], D("Problems found (empty when healthy).")]
    auto_fixable: Annotated[int, D("How many findings fix=true can repair.")]
    review: Annotated[int, D("How many need manual review.")]
    applied: Annotated[int, D("Fixes applied in this call.")]


class SkillInstallResult(TypedDict):
    skill: Annotated[str, D("Skill name (grove).")]
    path: Annotated[str, D("Where the skill folder is (or would be) installed.")]
    mode: Annotated[Literal["created", "updated", "unchanged"], D("created: new; updated: overwritten (force or missing files); unchanged: already identical.")]
    files: Annotated[List[str], D("Files of the skill, relative to its folder.")]
    dry_run: Annotated[bool, D("True when nothing was written (preview).")]


class RepoRow(TypedDict):
    path: Annotated[str, D("Absolute path of the repo (the folder containing .bare/): pass it as cwd.")]
    name: Annotated[str, D("Folder name.")]
    origin: Annotated[Optional[str], D("URL git uses for origin (`git remote get-url`, url.insteadOf applied: the SSH alias when a zone rewrites it), or null.")]
    base: Annotated[Optional[str], D("Base branch: default_base from .bare/grove.toml, else the bare HEAD; null if unknown.")]
    profile: Annotated[Optional[str], D("Effective profile: the one in .bare/grove.toml, else 'default' (as grove loads it).")]


class ReposResult(TypedDict):
    roots: Annotated[List[str], D("Folders searched.")]
    source: Annotated[Literal["paths", "default"], D("paths: given explicitly; default: the identity zones from `gwt ssh add` plus repos_roots from ~/.config/grove/config.toml.")]
    depth: Annotated[int, D("Search depth under each root.")]
    repos: Annotated[List[RepoRow], D("Managed repos found, sorted by path.")]
    count: Annotated[int, D("Number of repos found.")]
    hint: Annotated[Optional[str], D("What to do when nothing (or no root) was found; null otherwise.")]


class SshRemoveResult(TypedDict):
    name: Annotated[str, D("Account alias removed.")]
    deleted_key: Annotated[bool, D("Whether the key files were deleted.")]
    dry_run: Annotated[bool, D("True when nothing was written (preview).")]
    steps: Annotated[List[str], D("What was done (or would be done).")]
