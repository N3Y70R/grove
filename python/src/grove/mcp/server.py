"""grove MCP server — worktree operations exposed as tools (stdio transport).

This is a thin facade over ``grove.core`` (see spec §13). It mirrors the
``gwt`` CLI: typed inputs, structured output (the same ``result`` shape as
``--json``), and destructive actions gated by a ``confirm`` boolean — no
interactive prompts.

It does not go out to the network and has no ticket-platform clients: ticket
keys/slugs arrive by parameter. Enrichment (e.g. fetching an issue title) is
the agent's job, composing its own connectors with these tools.

Run with the ``grove-mcp`` entry point, or ``python -m grove.mcp``.
Requires the optional extra: ``pip install "grove-wt[mcp]"``.

Discoverability note: every tool carries per-parameter descriptions, enums for
constrained choices, and MCP annotations (read-only / destructive / offline) so
an agent can choose the right tool and arguments without trial and error. Keep
this enrichment in sync whenever a tool or its parameters change.
"""

from typing import Annotated, Any, List, Literal, Optional

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations
    from pydantic import Field
except ModuleNotFoundError as exc:  # pragma: no cover
    # ImportError (not SystemExit) so importers like pytest report it cleanly.
    try:
        import mcp as _mcp_pkg  # noqa: F401
    except ModuleNotFoundError:
        _hint = "The MCP SDK is not installed."
    else:
        _hint = "Incompatible MCP SDK version (grove requires mcp>=2.2,<3)."
    raise ImportError(
        f"{_hint} Install the optional extra:\n"
        '    pip install "grove-wt[mcp]"'
    ) from exc

from . import _ops
from ..core.errors import UsageError

mcp = MCPServer(name="grove")

# Reusable parameter annotations -------------------------------------------- #

Cwd = Annotated[Optional[str], Field(
    description="Absolute path to the managed repo (a folder containing .bare/). "
                "Defaults to the process working directory; always pass it explicitly "
                "when driving grove from chat.")]

# Every tool returns `dict[str, Any]` (not bare `dict`): with that type the SDK
# sends `structured_content` plus the same data as JSON text, and publishes an
# object output schema. A bare `dict` would only send text.

# Annotation presets (open_world_hint=False: grove is offline, pure-git).
def _ann(title, *, read_only=False, destructive=False, idempotent=False):
    return ToolAnnotations(title=title, read_only_hint=read_only,
                           destructive_hint=destructive, idempotent_hint=idempotent,
                           open_world_hint=False)


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
) -> dict[str, Any]:
    """Initialize a managed repo (bare model + base worktree) from an origin URL.

    Applies a policy profile (default if omitted), auto-detects the base branch
    from the origin when the configured one is absent, and writes .bare/grove.toml.
    Transactional: on failure the partial folder is removed (unless keep_on_error).

    CLI: `gwt setup <url> [--profile P] [--base B] [--ssh-alias A]`
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
    profile: Annotated[Optional[str], Field(description="Policy profile to apply and record in .bare/grove.toml: default | personal | gitflow | a custom one. Default: default.")] = None,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Adopt/convert an existing normal clone into grove's bare + worktrees model
    (no re-clone). Use this when the user already has the repo cloned.

    In-place by default (reuses .git, auto-stashes and restores uncommitted work,
    moves ignored files — also those nested in tracked folders — into the current
    worktree; conflicts are kept at the root and reported). Writes .bare/grove.toml
    with the chosen profile and the detected base. `into` builds a fresh grove repo beside the source,
    leaving it untouched. Submodules/Git LFS are refused unless force=true.
    With `into`, a failed conversion cleans up the new folder (unless keep_on_error).

    CLI: `gwt convert [path] [--into DIR] [--profile P]` (alias `gwt adopt`)
    """
    return _ops.op_convert(path=path, into=into, branches=branches, fetch=fetch,
                           force=force, git_pointer=git_pointer,
                           keep_on_error=keep_on_error, dry_run=dry_run,
                           profile=profile, cwd=cwd)


@mcp.tool(annotations=_ann("List worktrees", read_only=True))
def grove_list(
    cwd: Cwd = None,
    type: Annotated[Optional[str], Field(description="Filter by type/kind (feature, hotfix, release, special, temp…).")] = None,
    dirty: Annotated[bool, Field(description="Only worktrees with uncommitted changes.")] = False,
    orphans: Annotated[bool, Field(description="Only orphan/prunable worktrees.")] = False,
) -> dict[str, Any]:
    """List the repo's worktrees with status (branch, ticket, ahead/behind, dirty).

    `ahead`/`behind` are measured against `compared_to`: the upstream, or the
    repo base for a branch with no upstream yet. The base worktree has
    kind="base". Paths are correct even when the repo is seen from another mount.

    Each row also carries `gitdir`: the worktree's internal admin dir relative to
    the repo root (e.g. .bare/worktrees/PROJ-1-login). Use it to build GIT_DIR
    when the repo is seen from another mount (the worktree's .git file holds an
    absolute path that may not exist there).

    CLI: `gwt list [--type T] [--dirty] [--orphans] --json`
    """
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
) -> dict[str, Any]:
    """Create a worktree (ticket, release or temp).

    The ticket key and slug are supplied by the caller; grove does not query any
    ticket system. Use 'base' to branch off a specific branch.

    CLI: `gwt create <TICKET> <type> "<name>" [--base B]` · `gwt create release <v>` · `gwt create temp <name>`
    """
    return _ops.op_create(kind=kind, type=type, name=name, ticket=ticket,
                          version=version, base=base, cwd=cwd)


@mcp.tool(annotations=_ann("Track an existing branch"))
def grove_track(
    branch: Annotated[str, Field(description="Existing branch name (local or on origin) to bring in.")],
    as_: Annotated[Optional[str], Field(description="Explicit destination path, e.g. 'hotfix/PROJ-1-fix', to relocate/force a type.")] = None,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Bring an existing branch (local or on origin) into the structure as a worktree.

    CLI: `gwt track <branch> [--as <type>/<TICKET>-<slug>]`
    """
    return _ops.op_track(branch=branch, as_=as_, cwd=cwd)


@mcp.tool(annotations=_ann("Remove a worktree", destructive=True))
def grove_remove(
    target: Annotated[Optional[str], Field(description="Ticket, branch or path of the worktree to remove.")] = None,
    merged: Annotated[bool, Field(description="Sweep ALL ticket worktrees already merged into the base.")] = False,
    delete_branch: Annotated[bool, Field(description="Also delete the local branch (if merged/pushed).")] = False,
    force: Annotated[bool, Field(description="Remove even if dirty; delete the branch even if not merged.")] = False,
    confirm: Annotated[bool, Field(description="Required: set true to actually remove (this is destructive). Not needed with dry_run.")] = False,
    dry_run: Annotated[bool, Field(description="Report what WOULD be removed without changing anything (no confirm needed). Use it before merged=true.")] = False,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Remove a worktree (DESTRUCTIVE — requires confirm=true, unless dry_run).

    Provide 'target' (ticket, branch or path), or merged=true to sweep all
    ticket worktrees already merged into the base (see the `merged` field of
    grove_list; a brand-new branch with no commits also counts as merged).
    Special worktrees are protected. Empty type folders left behind are removed.

    CLI: `gwt remove <target> [--delete-branch] [--force] [--dry-run]` · `gwt remove --merged [--dry-run]`
    """
    return _ops.op_remove(target=target, merged=merged, delete_branch=delete_branch,
                          force=force, confirm=confirm, dry_run=dry_run, cwd=cwd)


@mcp.tool(annotations=_ann("Reset a worktree to origin (DISCARDS local work)", destructive=True))
def grove_reset(
    target: Annotated[Optional[str], Field(description="Ticket/branch/path of the worktree (default: current one).")] = None,
    clean: Annotated[bool, Field(description="Also delete untracked files (git clean -fd).")] = False,
    confirm: Annotated[bool, Field(description="Required: set true to proceed (discards local commits/changes).")] = False,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """DISCARDS local commits and changes: reset a worktree to its origin branch
    (fetch + reset --hard). Requires confirm=true.

    For branches that are regenerated/force-pushed. To only BRING remote changes
    without losing anything, use grove_fetch instead.

    CLI: `gwt reset [target] [--clean] [--yes]`
    """
    return _ops.op_reset(target=target, clean=clean, confirm=confirm, cwd=cwd)


@mcp.tool(annotations=_ann("DEPRECATED alias of grove_reset", destructive=True))
def grove_sync(
    target: Annotated[Optional[str], Field(description="Ticket/branch/path of the worktree (default: current one).")] = None,
    clean: Annotated[bool, Field(description="Also delete untracked files (git clean -fd).")] = False,
    confirm: Annotated[bool, Field(description="Required: set true to proceed (discards local commits/changes).")] = False,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """DEPRECATED — use grove_reset. DISCARDS local commits and changes (reset --hard
    to origin). To only bring remote changes, use grove_fetch.

    CLI: `gwt sync` (deprecated) → `gwt reset`
    """
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
) -> dict[str, Any]:
    """Merge branches into the shared integration branch, or create it from a base.

    Additive (default) requires the branch to exist. regenerate=true rebuilds it
    from 'base'; if it already exists this force-pushes (requires confirm=true),
    and if it does NOT exist grove creates it from 'base' with a normal push
    (no confirm needed). The result carries 'created' (bool) and 'mode'
    (created | regenerate | additive).

    CLI: `gwt publish [targets…] [--into B] [--regenerate] [--base B]`
    """
    return _ops.op_publish(targets=targets, into=into, regenerate=regenerate,
                           base=base, no_sync=no_sync, confirm=confirm, cwd=cwd)


@mcp.tool(annotations=_ann("Diagnose/fix worktree hygiene", idempotent=True))
def grove_doctor(
    fix: Annotated[bool, Field(description="Apply the auto-fixable issues (otherwise report only).")] = False,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Diagnose worktree hygiene problems; set fix=true to apply auto-fixable ones.

    Besides structure (orphans, naming, upstreams, root .git pointer) it finds
    orphaned git locks (*.lock) and leftover temp objects in .bare — auto-fixable
    once stale (≥60s with no git running, or ≥10min) — and worktrees where git
    has no author identity (commits would fail; manual).

    CLI: `gwt doctor [--fix] [--dry-run]`
    """
    return _ops.op_doctor(fix=fix, cwd=cwd)


@mcp.tool(annotations=_ann("Fetch from origin (never touches worktrees)", idempotent=True))
def grove_fetch(
    prune: Annotated[bool, Field(description="Also drop origin/* refs of branches deleted on the remote (git fetch --prune).")] = False,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Bring what's new on origin and report each worktree's ahead/behind — the
    SAFE way to update from the remote: it only updates origin/* refs and never
    modifies any worktree (unlike grove_reset, which discards local work).

    Each row: worktree, branch, compared_to, ahead, behind, status
    (in sync | ahead | behind | diverged), dirty.

    CLI: `gwt fetch [--prune]`
    """
    return _ops.op_fetch(prune=prune, cwd=cwd)


@mcp.tool(annotations=_ann("Compare branches (ahead/behind)", read_only=True))
def grove_compare(
    a: Annotated[Optional[str], Field(description="Worktree/branch A (default: current worktree).")] = None,
    b: Annotated[Optional[str], Field(description="Worktree/branch B (default: A's upstream).")] = None,
    vs: Annotated[Optional[str], Field(description="Compare ALL worktrees against this ref.")] = None,
    fetch: Annotated[bool, Field(description="git fetch origin first: the SAFE way to bring remote changes (updates origin/* refs, never touches worktrees).")] = False,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Ahead/behind between branches/worktrees. With fetch=true it first runs
    `git fetch origin` — the safe way to bring remote changes (it never modifies
    your worktrees; unlike grove_reset, which discards local work).

    CLI: `gwt compare [a] [b] [--vs REF] [--fetch]`
    """
    return _ops.op_compare(a=a, b=b, vs=vs, fetch=fetch, cwd=cwd)


@mcp.tool(annotations=_ann("Show / set repo configuration", idempotent=True))
def grove_config(
    set_ssh_alias: Annotated[Optional[str], Field(description="If given, set the repo's SSH alias and rewrite origin (or 'none' to clear). Omit to just show config.")] = None,
    set_key: Annotated[Optional[str], Field(description="A grove.toml key to set (e.g. 'default_base', 'tickets', 'allowed_types', 'integration_branch'). Requires set_value.")] = None,
    set_value: Annotated[Optional[str], Field(description="Value for set_key. For list keys (allowed_types, special_worktrees, ticket_prefixes, known_git_hosts) use a comma-separated string.")] = None,
    unset_key: Annotated[Optional[str], Field(description="A grove.toml key to remove (reverts to the profile/default value).")] = None,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Show the repo configuration, or change it: set the SSH alias (rewrites
    origin), set an arbitrary grove.toml key, or unset one. Omit all of these to
    just show the current config.

    CLI: `gwt config show | set <key> <value> | unset <key> | edit | set-ssh-alias <alias>`
    """
    if set_ssh_alias is not None:
        return _ops.op_config_set_ssh_alias(value=set_ssh_alias, cwd=cwd)
    if set_key is not None:
        if set_value is None:
            raise UsageError("set_value is required when set_key is given.")
        return _ops.op_config_set(key=set_key, value=set_value, cwd=cwd)
    if unset_key is not None:
        return _ops.op_config_unset(key=unset_key, cwd=cwd)
    return _ops.op_config_show(cwd=cwd)


@mcp.tool(annotations=_ann("Diagnose SSH for a remote", read_only=True))
def grove_ssh_check(
    target: Annotated[Optional[str], Field(description="URL or host to diagnose (default: the current repo's origin).")] = None,
    all: Annotated[bool, Field(description="Diagnose every Host in ~/.ssh/config.")] = False,
    live: Annotated[bool, Field(description="Actually test authentication (ssh -T).")] = False,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """Diagnose SSH config for a git remote (keys, agent, permissions).

    CLI: `gwt ssh check [target] [--all] [--live]`
    """
    return _ops.op_ssh_check(target=target, all=all, live=live, cwd=cwd)


@mcp.tool(annotations=_ann("Map a repo/host to SSH aliases", read_only=True))
def grove_ssh_aliases(
    target: Annotated[Optional[str], Field(description="URL or host to map (default: the current repo's origin). Use this to discover which ~/.ssh/config alias a repo should use.")] = None,
    cwd: Cwd = None,
) -> dict[str, Any]:
    """List the ~/.ssh/config aliases that resolve to a repo's host (the
    repo↔alias map), marking which one is currently applied. Read-only.

    CLI: `gwt ssh aliases [url-or-host]`
    """
    return _ops.op_ssh_aliases(target=target, cwd=cwd)


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
) -> dict[str, Any]:
    """Provision an SSH account (machine-level): generate an ed25519 key, write the
    ~/.ssh/config Host alias, and wire folder-scoped git identity.

    grove never uploads the key — the returned 'pubkey' must be uploaded to the
    host by you (e.g. via your GitHub/Bitbucket connector). Idempotent.

    CLI: `gwt ssh add <name> --host <host> [--email E] [--scope-dir DIR]`
    """
    return _ops.op_ssh_add(name, host=host, email=email, scope_dir=scope_dir,
                           key=key, no_identity=no_identity, no_agent=no_agent,
                           no_passphrase=no_passphrase, dry_run=dry_run)


@mcp.tool(annotations=_ann("List SSH accounts", read_only=True))
def grove_ssh_accounts() -> dict[str, Any]:
    """List grove-managed SSH accounts and zones (alias, host, key, routing coherence).

    CLI: `gwt ssh accounts`
    """
    return _ops.op_ssh_accounts()


@mcp.tool(annotations=_ann("Diagnose/fix SSH multi-account setup", idempotent=True))
def grove_ssh_doctor(
    fix: Annotated[bool, Field(description="Apply the auto-fixable items (otherwise report only).")] = False,
) -> dict[str, Any]:
    """Diagnose the SSH/git multi-account setup; set fix=true to apply auto-fixable items.

    Reports the host-vs-alias trap, embedded secrets, missing IdentitiesOnly/insteadOf,
    bad key permissions, unset useConfigOnly, orphans, etc. (auto-fixes the safe ones).

    CLI: `gwt ssh doctor [--fix]`
    """
    return _ops.op_ssh_doctor(fix=fix)


@mcp.tool(annotations=_ann("Remove an SSH account", destructive=True))
def grove_ssh_remove(
    name: Annotated[str, Field(description="Account alias to remove.")],
    delete_key: Annotated[bool, Field(description="Also delete the key files (kept by default).")] = False,
    keep_routing: Annotated[bool, Field(description="Keep the git identity routing for the zone.")] = False,
    confirm: Annotated[bool, Field(description="Required: set true to proceed (edits ~/.ssh/config and ~/.gitconfig).")] = False,
    dry_run: Annotated[bool, Field(description="Preview the edits without applying them.")] = False,
) -> dict[str, Any]:
    """Remove a grove-managed SSH account (DESTRUCTIVE — requires confirm=true).

    CLI: `gwt ssh remove <name> [--delete-key]`
    """
    return _ops.op_ssh_remove(name, delete_key=delete_key, keep_routing=keep_routing,
                              confirm=confirm, dry_run=dry_run)


def main() -> None:
    """Entry point: start the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
