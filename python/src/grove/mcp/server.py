"""grove MCP server — worktree operations exposed as tools (stdio transport).

This is a thin facade over ``grove.core`` (see spec §13). It mirrors the
``gwt`` CLI: typed inputs, structured output (the same ``result`` shape as
``--json``), and destructive actions gated by a ``confirm`` boolean — no
interactive prompts.

It does not go out to the network and has no ticket-platform clients: ticket
keys/slugs arrive by parameter. Enrichment (e.g. fetching an issue title) is
the agent's job, composing its own connectors with these tools.

Run with the ``grove-mcp`` entry point, or ``python -m grove.mcp``.
Requires the optional extra: ``pip install "grove[mcp]"``.

Discoverability note: every tool carries per-parameter descriptions, enums for
constrained choices, and MCP annotations (read-only / destructive / offline) so
an agent can choose the right tool and arguments without trial and error. Keep
this enrichment in sync whenever a tool or its parameters change.
"""

from typing import Annotated, List, Literal, Optional

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    from pydantic import Field
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit(
        "The MCP SDK is not installed. Install the optional extra:\n"
        '    pip install "grove[mcp]"'
    ) from exc

from . import _ops

mcp = FastMCP("grove")

# Reusable parameter annotations -------------------------------------------- #

Cwd = Annotated[Optional[str], Field(
    description="Absolute path to the managed repo (a folder containing .bare/). "
                "Defaults to the process working directory; always pass it explicitly "
                "when driving grove from chat.")]

# Annotation presets (openWorldHint=False: grove is offline, pure-git).
def _ann(title, *, read_only=False, destructive=False, idempotent=False):
    return ToolAnnotations(title=title, readOnlyHint=read_only,
                           destructiveHint=destructive, idempotentHint=idempotent,
                           openWorldHint=False)


@mcp.tool(annotations=_ann("Set up a managed repo"))
def grove_setup(
    url: Annotated[str, Field(description="Origin URL to clone (SSH or HTTPS).")],
    name: Annotated[Optional[str], Field(description="Repo folder name (default: derived from the URL).")] = None,
    into: Annotated[Optional[str], Field(description="Parent directory to create the repo folder in (default: cwd).")] = None,
    profile: Annotated[Optional[str], Field(description="Policy profile: default | personal | gitflow | a custom one.")] = None,
    base: Annotated[Optional[str], Field(description="Base branch override. If omitted, uses the profile's base and falls back to the origin's default branch (e.g. 'production' instead of 'main').")] = None,
    ssh_alias: Annotated[Optional[str], Field(description="~/.ssh/config alias to rewrite the origin host with (or 'none').")] = None,
    git_pointer: Annotated[bool, Field(description="Write the root .git pointer (gitdir: ./.bare) so plain git works from the repo root. Default true.")] = True,
    keep_on_error: Annotated[bool, Field(description="If setup fails midway, keep the partial folder instead of removing it. Default false (clean up so a retry starts fresh).")] = False,
    cwd: Cwd = None,
) -> dict:
    """Initialize a managed repo (bare model + base worktree) from an origin URL.

    Applies a policy profile (default if omitted), auto-detects the base branch
    from the origin when the configured one is absent, and writes .bare/grove.toml.
    Transactional: on failure the partial folder is removed (unless keep_on_error).
    """
    return _ops.op_setup(url, name=name, into=into, profile=profile,
                         base=base, ssh_alias=ssh_alias, git_pointer=git_pointer,
                         keep_on_error=keep_on_error, cwd=cwd)


@mcp.tool(annotations=_ann("Convert an existing clone to the grove model"))
def grove_convert(
    path: Annotated[Optional[str], Field(description="Path of the existing normal clone to convert (default: cwd).")] = None,
    into: Annotated[Optional[str], Field(description="Create a NEW grove repo here and leave the source clone untouched (no WIP carried). Omit for in-place.")] = None,
    branches: Annotated[Literal["current", "current+base", "all"], Field(description="Which worktrees to materialize.")] = "current+base",
    fetch: Annotated[bool, Field(description="Contact origin (fetch). Set false for fully offline.")] = True,
    force: Annotated[bool, Field(description="Proceed even if submodules or Git LFS are detected (blocked by default).")] = False,
    git_pointer: Annotated[bool, Field(description="Write the root .git pointer (gitdir: ./.bare). Default true.")] = True,
    keep_on_error: Annotated[bool, Field(description="If conversion fails midway, keep partial output. Default false: with --into the new folder is removed; in-place stops and reports (never auto-deletes user files).")] = False,
    dry_run: Annotated[bool, Field(description="Return the plan without making changes.")] = False,
    cwd: Cwd = None,
) -> dict:
    """Convert an existing normal clone into grove's bare + worktrees model.

    In-place by default (reuses .git, auto-stashes and restores uncommitted work,
    keeps ignored files). `into` builds a fresh grove repo beside the source,
    leaving it untouched. Submodules/Git LFS are refused unless force=true.
    With `into`, a failed conversion cleans up the new folder (unless keep_on_error).
    """
    return _ops.op_convert(path=path, into=into, branches=branches, fetch=fetch,
                           force=force, git_pointer=git_pointer,
                           keep_on_error=keep_on_error, dry_run=dry_run, cwd=cwd)


@mcp.tool(annotations=_ann("List worktrees", read_only=True))
def grove_list(
    cwd: Cwd = None,
    type: Annotated[Optional[str], Field(description="Filter by type/kind (feature, hotfix, release, special, temp…).")] = None,
    dirty: Annotated[bool, Field(description="Only worktrees with uncommitted changes.")] = False,
    orphans: Annotated[bool, Field(description="Only orphan/prunable worktrees.")] = False,
) -> dict:
    """List the repo's worktrees with status (branch, ticket, ahead/behind, dirty)."""
    return _ops.op_list(cwd=cwd, type=type, dirty=dirty, orphans=orphans)


@mcp.tool(annotations=_ann("Create a worktree"))
def grove_create(
    kind: Annotated[Literal["ticket", "release", "temp"], Field(
        description="ticket: feature/hotfix/bugfix worktree; release: release/<version>; temp: throwaway worktree.")] = "ticket",
    type: Annotated[Optional[str], Field(description="For kind=ticket: the type (feature/hotfix/bugfix…).")] = None,
    name: Annotated[Optional[str], Field(description="Human description/slug (kind=ticket or temp). grove normalizes it.")] = None,
    ticket: Annotated[Optional[str], Field(description="Ticket key e.g. PROJ-123 (kind=ticket; required/optional per repo policy).")] = None,
    version: Annotated[Optional[str], Field(description="Version for kind=release, e.g. v1.2.0.")] = None,
    base: Annotated[Optional[str], Field(description="Branch to start from. Say 'from <branch>' → this. Works for all kinds, including temp. Omit for the repo's default base.")] = None,
    cwd: Cwd = None,
) -> dict:
    """Create a worktree (ticket, release or temp).

    The ticket key and slug are supplied by the caller; grove does not query any
    ticket system. Use 'base' to branch off a specific branch.
    """
    return _ops.op_create(kind=kind, type=type, name=name, ticket=ticket,
                          version=version, base=base, cwd=cwd)


@mcp.tool(annotations=_ann("Track an existing branch"))
def grove_track(
    branch: Annotated[str, Field(description="Existing branch name (local or on origin) to bring in.")],
    as_: Annotated[Optional[str], Field(description="Explicit destination path, e.g. 'hotfix/PROJ-1-fix', to relocate/force a type.")] = None,
    cwd: Cwd = None,
) -> dict:
    """Bring an existing branch (local or on origin) into the structure as a worktree."""
    return _ops.op_track(branch=branch, as_=as_, cwd=cwd)


@mcp.tool(annotations=_ann("Remove a worktree", destructive=True))
def grove_remove(
    target: Annotated[Optional[str], Field(description="Ticket, branch or path of the worktree to remove.")] = None,
    merged: Annotated[bool, Field(description="Sweep ALL ticket worktrees already merged into the base.")] = False,
    delete_branch: Annotated[bool, Field(description="Also delete the local branch (if merged/pushed).")] = False,
    force: Annotated[bool, Field(description="Remove even if dirty; delete the branch even if not merged.")] = False,
    confirm: Annotated[bool, Field(description="Required: set true to actually remove (this is destructive).")] = False,
    cwd: Cwd = None,
) -> dict:
    """Remove a worktree (DESTRUCTIVE — requires confirm=true).

    Provide 'target' (ticket, branch or path), or merged=true to sweep all
    ticket worktrees already merged into the base. Special worktrees are protected.
    """
    return _ops.op_remove(target=target, merged=merged, delete_branch=delete_branch,
                          force=force, confirm=confirm, cwd=cwd)


@mcp.tool(annotations=_ann("Re-sync a worktree (reset --hard)", destructive=True))
def grove_sync(
    target: Annotated[Optional[str], Field(description="Ticket/branch/path of the worktree (default: current one).")] = None,
    clean: Annotated[bool, Field(description="Also delete untracked files (git clean -fd).")] = False,
    confirm: Annotated[bool, Field(description="Required: set true to proceed (discards local commits/changes).")] = False,
    cwd: Cwd = None,
) -> dict:
    """Re-sync a worktree to its origin branch via reset --hard (DESTRUCTIVE — requires confirm=true)."""
    return _ops.op_sync(target=target, clean=clean, confirm=confirm, cwd=cwd)


@mcp.tool(annotations=_ann("Publish to / create the integration branch", destructive=True))
def grove_publish(
    targets: Annotated[List[str], Field(description="Tickets or branches to merge in. May be empty with regenerate=true to seed an empty integration branch.")] = [],  # noqa: B006
    into: Annotated[Optional[str], Field(description="Integration branch name (default: repo's integration_branch, e.g. temporary-unified-test).")] = None,
    regenerate: Annotated[bool, Field(description="Rebuild from base; also CREATES the branch from base if it doesn't exist yet.")] = False,
    base: Annotated[Optional[str], Field(description="Base branch for regenerate/creation (default: repo base). Say 'from <branch>' → this.")] = None,
    no_sync: Annotated[bool, Field(description="Additive mode: don't sync the integration branch before merging.")] = False,
    confirm: Annotated[bool, Field(description="Required only when regenerating an EXISTING branch (force-push). Not needed for first-time creation.")] = False,
    cwd: Cwd = None,
) -> dict:
    """Merge branches into the shared integration branch, or create it from a base.

    Additive (default) requires the branch to exist. regenerate=true rebuilds it
    from 'base'; if it already exists this force-pushes (requires confirm=true),
    and if it does NOT exist grove creates it from 'base' with a normal push
    (no confirm needed). The result carries 'created' (bool) and 'mode'
    (created | regenerate | additive).
    """
    return _ops.op_publish(targets=targets, into=into, regenerate=regenerate,
                           base=base, no_sync=no_sync, confirm=confirm, cwd=cwd)


@mcp.tool(annotations=_ann("Diagnose/fix worktree hygiene", idempotent=True))
def grove_doctor(
    fix: Annotated[bool, Field(description="Apply the auto-fixable issues (otherwise report only).")] = False,
    cwd: Cwd = None,
) -> dict:
    """Diagnose worktree hygiene problems; set fix=true to apply auto-fixable ones."""
    return _ops.op_doctor(fix=fix, cwd=cwd)


@mcp.tool(annotations=_ann("Compare branches (ahead/behind)", read_only=True))
def grove_compare(
    a: Annotated[Optional[str], Field(description="Worktree/branch A (default: current worktree).")] = None,
    b: Annotated[Optional[str], Field(description="Worktree/branch B (default: A's upstream).")] = None,
    vs: Annotated[Optional[str], Field(description="Compare ALL worktrees against this ref.")] = None,
    fetch: Annotated[bool, Field(description="git fetch origin before comparing.")] = False,
    cwd: Cwd = None,
) -> dict:
    """Read-only sync status between branches/worktrees (ahead/behind)."""
    return _ops.op_compare(a=a, b=b, vs=vs, fetch=fetch, cwd=cwd)


@mcp.tool(annotations=_ann("Show / set repo configuration"))
def grove_config(
    set_ssh_alias: Annotated[Optional[str], Field(description="If given, set the repo's SSH alias and rewrite origin (or 'none' to clear). Omit to just show config.")] = None,
    cwd: Cwd = None,
) -> dict:
    """Show the repo configuration, or set the SSH alias (rewrites origin)."""
    if set_ssh_alias is not None:
        return _ops.op_config_set_ssh_alias(value=set_ssh_alias, cwd=cwd)
    return _ops.op_config_show(cwd=cwd)


@mcp.tool(annotations=_ann("Diagnose SSH for a remote", read_only=True))
def grove_ssh_check(
    target: Annotated[Optional[str], Field(description="URL or host to diagnose (default: the current repo's origin).")] = None,
    all: Annotated[bool, Field(description="Diagnose every Host in ~/.ssh/config.")] = False,
    live: Annotated[bool, Field(description="Actually test authentication (ssh -T).")] = False,
    cwd: Cwd = None,
) -> dict:
    """Diagnose SSH config for a git remote (keys, agent, permissions)."""
    return _ops.op_ssh_check(target=target, all=all, live=live, cwd=cwd)


@mcp.tool(annotations=_ann("Provision an SSH account", idempotent=True))
def grove_ssh_add(
    name: Annotated[str, Field(description="Alias name for the account, e.g. 'work-gh'.")],
    host: Annotated[str, Field(description="Real host, e.g. github.com or bitbucket.org.")],
    email: Annotated[Optional[str], Field(description="Git identity email for this account's folder zone (required for identity routing).")] = None,
    scope_dir: Annotated[Optional[str], Field(description="Folder that should use this account (e.g. /Users/me/work).")] = None,
    key: Annotated[Optional[str], Field(description="Reuse an existing private key path instead of generating one.")] = None,
    no_identity: Annotated[bool, Field(description="Only the SSH Host block; skip git identity routing.")] = False,
    no_agent: Annotated[bool, Field(description="Don't load the key into the ssh-agent.")] = False,
    no_passphrase: Annotated[bool, Field(description="Generate the key without a passphrase (default true; no TTY here).")] = True,
    dry_run: Annotated[bool, Field(description="Preview the edits without applying them.")] = False,
) -> dict:
    """Provision an SSH account (machine-level): generate an ed25519 key, write the
    ~/.ssh/config Host alias, and wire folder-scoped git identity.

    grove never uploads the key — the returned 'pubkey' must be uploaded to the
    host by you (e.g. via your GitHub/Bitbucket connector). Idempotent.
    """
    return _ops.op_ssh_add(name, host=host, email=email, scope_dir=scope_dir,
                           key=key, no_identity=no_identity, no_agent=no_agent,
                           no_passphrase=no_passphrase, dry_run=dry_run)


@mcp.tool(annotations=_ann("List SSH accounts", read_only=True))
def grove_ssh_accounts() -> dict:
    """List grove-managed SSH accounts and zones (alias, host, key, routing coherence)."""
    return _ops.op_ssh_accounts()


@mcp.tool(annotations=_ann("Diagnose/fix SSH multi-account setup", idempotent=True))
def grove_ssh_doctor(
    fix: Annotated[bool, Field(description="Apply the auto-fixable items (otherwise report only).")] = False,
) -> dict:
    """Diagnose the SSH/git multi-account setup; set fix=true to apply auto-fixable items.

    Reports the host-vs-alias trap, embedded secrets, missing IdentitiesOnly/insteadOf,
    bad key permissions, unset useConfigOnly, orphans, etc. (auto-fixes the safe ones).
    """
    return _ops.op_ssh_doctor(fix=fix)


@mcp.tool(annotations=_ann("Remove an SSH account", destructive=True))
def grove_ssh_remove(
    name: Annotated[str, Field(description="Account alias to remove.")],
    delete_key: Annotated[bool, Field(description="Also delete the key files (kept by default).")] = False,
    keep_routing: Annotated[bool, Field(description="Keep the git identity routing for the zone.")] = False,
    confirm: Annotated[bool, Field(description="Required: set true to proceed (edits ~/.ssh/config and ~/.gitconfig).")] = False,
    dry_run: Annotated[bool, Field(description="Preview the edits without applying them.")] = False,
) -> dict:
    """Remove a grove-managed SSH account (DESTRUCTIVE — requires confirm=true)."""
    return _ops.op_ssh_remove(name, delete_key=delete_key, keep_routing=keep_routing,
                              confirm=confirm, dry_run=dry_run)


def main() -> None:
    """Entry point: start the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
