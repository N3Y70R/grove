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
"""

from __future__ import annotations

from typing import List, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit(
        "The MCP SDK is not installed. Install the optional extra:\n"
        '    pip install "grove[mcp]"'
    ) from exc

from . import _ops

mcp = FastMCP("grove")


@mcp.tool()
def grove_setup(
    url: str,
    name: Optional[str] = None,
    into: Optional[str] = None,
    profile: Optional[str] = None,
    base: Optional[str] = None,
    ssh_alias: Optional[str] = None,
    cwd: Optional[str] = None,
) -> dict:
    """Initialize a managed repo (bare model + base worktree) from an origin URL.

    Applies a policy profile (default if omitted) and writes .bare/grove.toml.
    'base' overrides the base branch; if omitted, grove uses the profile's base
    and falls back to the origin's default branch when that base doesn't exist
    (e.g. repos whose base is 'production', not 'main').
    """
    return _ops.op_setup(url, name=name, into=into, profile=profile,
                         base=base, ssh_alias=ssh_alias, cwd=cwd)


@mcp.tool()
def grove_list(
    cwd: Optional[str] = None,
    type: Optional[str] = None,
    dirty: bool = False,
    orphans: bool = False,
) -> dict:
    """List the repo's worktrees with status (branch, ticket, ahead/behind, dirty).

    Optional filters: by type/kind, only dirty, or only orphan/prunable.
    """
    return _ops.op_list(cwd=cwd, type=type, dirty=dirty, orphans=orphans)


@mcp.tool()
def grove_create(
    kind: str = "ticket",
    type: Optional[str] = None,
    name: Optional[str] = None,
    ticket: Optional[str] = None,
    version: Optional[str] = None,
    base: Optional[str] = None,
    cwd: Optional[str] = None,
) -> dict:
    """Create a worktree.

    kind='ticket' (default): needs 'type' (e.g. feature/hotfix/bugfix) and
    'name'; 'ticket' (e.g. PROJ-123) is required/optional per repo policy.
    kind='release': needs 'version'. kind='temp': needs 'name'.
    'base' branches the new worktree off a specific branch (works for all
    kinds, including temp); omit it to use the repo's default base.
    The ticket key and slug are supplied by the caller; grove does not query
    any ticket system.
    """
    return _ops.op_create(kind=kind, type=type, name=name, ticket=ticket,
                          version=version, base=base, cwd=cwd)


@mcp.tool()
def grove_track(
    branch: str,
    as_: Optional[str] = None,
    cwd: Optional[str] = None,
) -> dict:
    """Bring an existing branch (local or on origin) into the structure as a worktree.

    Use 'as_' (e.g. 'hotfix/PROJ-1-fix') to set an explicit destination.
    """
    return _ops.op_track(branch=branch, as_=as_, cwd=cwd)


@mcp.tool()
def grove_remove(
    target: Optional[str] = None,
    merged: bool = False,
    delete_branch: bool = False,
    force: bool = False,
    confirm: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    """Remove a worktree (DESTRUCTIVE — set confirm=true to proceed).

    Provide 'target' (ticket, branch or path), or merged=true to sweep all
    ticket worktrees already merged into the base.
    """
    return _ops.op_remove(target=target, merged=merged, delete_branch=delete_branch,
                          force=force, confirm=confirm, cwd=cwd)


@mcp.tool()
def grove_sync(
    target: Optional[str] = None,
    clean: bool = False,
    confirm: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    """Re-sync a worktree to its origin branch via reset --hard (DESTRUCTIVE).

    Discards local commits/changes; set confirm=true to proceed.
    """
    return _ops.op_sync(target=target, clean=clean, confirm=confirm, cwd=cwd)


@mcp.tool()
def grove_publish(
    targets: List[str],
    into: Optional[str] = None,
    regenerate: bool = False,
    base: Optional[str] = None,
    no_sync: bool = False,
    confirm: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    """Merge branches into the shared integration branch and push.

    Additive by default (requires the integration branch to exist). regenerate=true
    rebuilds it from 'base'; if the branch already exists this force-pushes
    (DESTRUCTIVE — requires confirm=true), and if it does NOT exist grove creates
    it from 'base' with a normal push (no confirm needed). With regenerate=true,
    'targets' may be empty to seed an empty integration branch from 'base'.
    """
    return _ops.op_publish(targets=targets, into=into, regenerate=regenerate,
                           base=base, no_sync=no_sync, confirm=confirm, cwd=cwd)


@mcp.tool()
def grove_doctor(fix: bool = False, cwd: Optional[str] = None) -> dict:
    """Diagnose worktree hygiene problems; set fix=true to apply auto-fixable ones."""
    return _ops.op_doctor(fix=fix, cwd=cwd)


@mcp.tool()
def grove_compare(
    a: Optional[str] = None,
    b: Optional[str] = None,
    vs: Optional[str] = None,
    fetch: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    """Read-only sync status between branches/worktrees (ahead/behind).

    Compare 'a' vs 'b' (b defaults to a's upstream), or vs=REF to compare all
    worktrees against REF. fetch=true updates from origin first.
    """
    return _ops.op_compare(a=a, b=b, vs=vs, fetch=fetch, cwd=cwd)


@mcp.tool()
def grove_config(
    set_ssh_alias: Optional[str] = None,
    cwd: Optional[str] = None,
) -> dict:
    """Show the repo configuration, or set the SSH alias (rewrites origin).

    Omit 'set_ssh_alias' to show config; pass an alias (or 'none') to set it.
    """
    if set_ssh_alias is not None:
        return _ops.op_config_set_ssh_alias(value=set_ssh_alias, cwd=cwd)
    return _ops.op_config_show(cwd=cwd)


@mcp.tool()
def grove_ssh_check(
    target: Optional[str] = None,
    all: bool = False,
    live: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    """Diagnose SSH config for a git remote (keys, agent, permissions).

    Defaults to the current repo's origin; pass 'target' (URL/host) or
    all=true for every Host in ~/.ssh/config. live=true tests authentication.
    """
    return _ops.op_ssh_check(target=target, all=all, live=live, cwd=cwd)


@mcp.tool()
def grove_ssh_add(
    name: str,
    host: str,
    email: Optional[str] = None,
    scope_dir: Optional[str] = None,
    key: Optional[str] = None,
    no_identity: bool = False,
    no_agent: bool = False,
    no_passphrase: bool = True,
    dry_run: bool = False,
) -> dict:
    """Provision an SSH account: generate an ed25519 key, write the ~/.ssh/config
    Host alias, and (unless no_identity) wire git identity routing for 'scope_dir'
    (includeIf + insteadOf + email) so repos under that folder use this account.

    Machine-level (no repo context). The key is generated WITHOUT a passphrase by
    default (no TTY here). grove never uploads the key — the returned 'pubkey' must
    be uploaded to the host by you, e.g. via your GitHub/Bitbucket connector.
    Identity routing requires 'email'. Use dry_run=true to preview the edits.
    """
    return _ops.op_ssh_add(name, host=host, email=email, scope_dir=scope_dir,
                           key=key, no_identity=no_identity, no_agent=no_agent,
                           no_passphrase=no_passphrase, dry_run=dry_run)


@mcp.tool()
def grove_ssh_accounts() -> dict:
    """List grove-managed SSH accounts and zones (alias, host, key, routing coherence)."""
    return _ops.op_ssh_accounts()


@mcp.tool()
def grove_ssh_doctor(fix: bool = False) -> dict:
    """Diagnose the SSH/git multi-account setup; set fix=true to apply auto-fixable items.

    Reports the host-vs-alias trap, embedded secrets, missing IdentitiesOnly/insteadOf,
    bad key permissions, unset useConfigOnly, orphans, etc. (auto-fixes the safe ones).
    """
    return _ops.op_ssh_doctor(fix=fix)


@mcp.tool()
def grove_ssh_remove(
    name: str,
    delete_key: bool = False,
    keep_routing: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    """Remove a grove-managed SSH account (edits ~/.ssh/config and ~/.gitconfig).

    Set confirm=true to proceed (or dry_run=true to preview). Keeps key files unless
    delete_key=true; keeps git routing if keep_routing=true.
    """
    return _ops.op_ssh_remove(name, delete_key=delete_key, keep_routing=keep_routing,
                              confirm=confirm, dry_run=dry_run)


def main() -> None:
    """Entry point: start the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
