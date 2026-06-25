"""Pure operation layer for the MCP facade.

Each function mirrors a CLI command but returns the **structured result**
(the same dict shape the CLI emits under ``--json`` in its ``result`` field).
There is no MCP SDK import here on purpose: this module is importable and
testable on its own, and ``server.py`` only wraps these functions as tools.

Design principles (see spec §13):
* Thin facade over ``grove.core`` — no logic duplicated here.
* No network of its own and no ticket-platform clients; ticket data arrives
  by parameter.
* No interactive prompts: destructive actions are gated by a ``confirm``
  boolean parameter.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..core import (
    compare as core_compare,
    config as core_config,
    create as core_create,
    doctor as core_doctor,
    publish as core_publish,
    remove as core_remove,
    setup as core_setup,
    sshalias,
    sshcheck,
    sshdoctor,
    sshprov,
    sync as core_sync,
    track as core_track,
)
from ..core.errors import UsageError
from ..core.gitrunner import GitRunner
from ..core.model import Worktree, list_worktrees
from ..core.repo import find_repo, RepoContext


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _git() -> GitRunner:
    return GitRunner()


def _enter(cwd: Optional[str]) -> RepoContext:
    """Locate the managed repo from ``cwd`` and load its policy."""
    base = Path(cwd).resolve() if cwd else Path.cwd()
    repo = find_repo(base)
    core_config.load(repo.bare)
    return repo


def _rel(repo: RepoContext, path) -> str:
    try:
        return str(Path(path).relative_to(repo.root)).replace("\\", "/")
    except (ValueError, AttributeError):
        return str(path)


def _origin(repo: RepoContext) -> Optional[str]:
    res = _git().run(["remote", "get-url", "origin"], cwd=repo.bare,
                     check=False, mutating=False)
    return res.stdout.strip() if res.returncode == 0 else None


def _wt_dict(wt: Worktree) -> dict:
    cls = wt.classification
    return {
        "path": str(wt.path),
        "rel_path": wt.rel_path,
        "branch": wt.branch,
        "bare": wt.is_bare,
        "detached": wt.is_detached,
        "prunable": wt.prunable,
        "exists": wt.exists,
        "ticket": cls.ticket if cls else None,
        "kind": cls.kind if cls else None,
        "type": cls.type if cls else None,
        "dirty": wt.dirty,
        "ahead": wt.ahead,
        "behind": wt.behind,
        "upstream": wt.upstream,
    }


def _target_worktree(git: GitRunner, repo: RepoContext, target: Optional[str]) -> Worktree:
    if target:
        return core_remove.resolve_target(git, repo, target)
    cwd = Path.cwd().resolve()
    for w in list_worktrees(git, repo, with_status=True):
        if w.is_bare or not w.branch:
            continue
        try:
            cwd.relative_to(w.path.resolve())
            return w
        except ValueError:
            continue
    raise UsageError("Specify 'target' (the worktree was not detected from the current directory).")


# --------------------------------------------------------------------------- #
# Operations (1:1 with the CLI commands)
# --------------------------------------------------------------------------- #

def op_setup(
    url: str,
    *,
    name: Optional[str] = None,
    into: Optional[str] = None,
    profile: Optional[str] = None,
    base: Optional[str] = None,
    ssh_alias: Optional[str] = None,
    cwd: Optional[str] = None,
) -> dict:
    git = _git()
    profile_name = profile or core_config.DEFAULT_PROFILE
    try:
        policy = core_config.resolve_profile(profile_name)
    except KeyError:
        raise UsageError(f"Unknown profile: '{profile_name}'.")
    core_config.apply_policy(policy)

    final_url = url
    if ssh_alias and ssh_alias.lower() not in ("none", "-"):
        host = sshalias.url_host(url)
        if host:
            final_url = sshalias.rewrite_host(url, ssh_alias)
            core_config.SSH_ALIAS = ssh_alias

    dest = Path(into).resolve() if into else (Path(cwd).resolve() if cwd else Path.cwd())
    ctx = core_setup.setup(git, final_url, into=dest, name=name,
                           base_branch=base or core_config.DEFAULT_BASE)
    # setup may have auto-detected a different base; record it before writing config.
    if ctx.base:
        core_config.DEFAULT_BASE = ctx.base
    core_config.write_repo_config(ctx.bare, core_config.effective_policy())
    return {"name": ctx.name, "root": str(ctx.root),
            "profile": profile_name, "base": core_config.DEFAULT_BASE}


def op_list(
    *,
    cwd: Optional[str] = None,
    type: Optional[str] = None,
    dirty: bool = False,
    orphans: bool = False,
) -> dict:
    git = _git()
    repo = _enter(cwd)
    rows = []
    for wt in list_worktrees(git, repo, with_status=True):
        if orphans and not (wt.prunable or not wt.exists):
            continue
        if dirty and not wt.dirty:
            continue
        if type:
            cls = wt.classification
            if type not in ((cls.kind if cls else None), (cls.type if cls else None)):
                continue
        rows.append(_wt_dict(wt))
    return {"count": len(rows), "worktrees": rows}


def op_create(
    *,
    kind: str = "ticket",
    type: Optional[str] = None,
    name: Optional[str] = None,
    ticket: Optional[str] = None,
    version: Optional[str] = None,
    base: Optional[str] = None,
    cwd: Optional[str] = None,
) -> dict:
    git = _git()
    repo = _enter(cwd)

    if kind == "release":
        if not version:
            raise UsageError("kind='release' requires 'version'.")
        path = core_create.create_release(git, repo, version=version, base=base)
    elif kind == "temp":
        if not name:
            raise UsageError("kind='temp' requires 'name'.")
        path = core_create.create_temp(git, repo, name=name, base=base)
    elif kind == "ticket":
        if not type or not name:
            raise UsageError("kind='ticket' requires 'type' and 'name'.")
        path = core_create.create_ticket(git, repo, type=type, name=name,
                                         ticket=ticket, base=base)
    else:
        raise UsageError(f"Unknown kind: '{kind}' (use ticket | release | temp).")

    rel = _rel(repo, path)
    return {"path": str(path), "rel_path": rel, "branch": rel}


def op_track(
    *,
    branch: str,
    as_: Optional[str] = None,
    cwd: Optional[str] = None,
) -> dict:
    git = _git()
    repo = _enter(cwd)
    warnings: List[str] = []
    path = core_track.track(git, repo, branch=branch, as_=as_, warn=warnings.append)
    return {"path": str(path), "rel_path": _rel(repo, path),
            "branch": branch, "warnings": warnings}


def op_remove(
    *,
    target: Optional[str] = None,
    merged: bool = False,
    delete_branch: bool = False,
    force: bool = False,
    confirm: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    if not confirm:
        raise UsageError("remove is destructive; set confirm=true to proceed.")
    git = _git()
    repo = _enter(cwd)

    if merged:
        removed = core_remove.sweep_merged(
            git, repo, delete_branch=delete_branch, force=force
        )
        return {"mode": "merged", "removed": [w.rel_path for w in removed]}

    if not target:
        raise UsageError("Specify 'target' (ticket, branch or path) or set merged=true.")
    wt = core_remove.resolve_target(git, repo, target)
    core_remove.remove_one(git, repo, wt, delete_branch=delete_branch, force=force)
    return {"mode": "single", "removed": [wt.rel_path], "delete_branch": delete_branch}


def op_sync(
    *,
    target: Optional[str] = None,
    clean: bool = False,
    confirm: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    if not confirm:
        raise UsageError("sync resets the worktree (discards local changes); set confirm=true.")
    git = _git()
    repo = _enter(cwd)
    wt = _target_worktree(git, repo, target)
    losses = []
    if wt.ahead:
        losses.append(f"{wt.ahead} local commit(s) not pushed")
    if wt.dirty:
        losses.append("uncommitted changes")
    upstream = core_sync.sync_worktree(git, repo, wt, clean=clean)
    return {"worktree": wt.rel_path, "upstream": upstream, "discarded": losses}


def op_publish(
    *,
    targets: List[str],
    into: Optional[str] = None,
    regenerate: bool = False,
    base: Optional[str] = None,
    no_sync: bool = False,
    confirm: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    git = _git()
    repo = _enter(cwd)
    integration = into or core_config.INTEGRATION_BRANCH
    if not integration:
        raise UsageError("No integration branch configured; pass 'into'.")
    if not targets and not regenerate:
        raise UsageError(
            "Specify at least one target, or set regenerate=true with 'base' to "
            "create the integration branch."
        )

    base = base or core_config.DEFAULT_BASE
    branches = [core_publish.resolve_branch(git, repo, t) for t in targets]
    int_path, created = core_publish.ensure_integration(
        git, repo, integration, create_base=(base if regenerate else None)
    )

    if regenerate and not created:
        # Rebuilding an existing branch force-pushes → require confirm.
        if not confirm:
            raise UsageError(
                f"regenerate force-pushes origin/{integration}; set confirm=true to proceed."
            )
        core_publish.publish_regenerate(git, repo, integration, int_path, branches, base=base)
        mode = "regenerate"
    elif regenerate and created:
        # Freshly created from base → merge targets and normal push (no force/confirm).
        core_publish.publish_additive(git, repo, integration, int_path, branches, no_sync=True)
        mode = "created"
    else:
        core_publish.publish_additive(git, repo, integration, int_path, branches,
                                      no_sync=no_sync)
        mode = "additive"
    return {"integration": integration, "mode": mode, "created": created,
            "branches": branches, "base": base}


def op_doctor(
    *,
    fix: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    git = _git()
    repo = _enter(cwd)
    issues = core_doctor.diagnose(git, repo)
    auto = [i for i in issues if i.fix is not None]
    manual = [i for i in issues if i.fix is None]
    applied = core_doctor.apply(issues) if (fix and auto) else 0
    return {
        "issues": [
            {"kind": i.kind, "severity": i.severity, "target": i.target,
             "message": i.message, "action": i.action, "fixable": i.fix is not None}
            for i in issues
        ],
        "auto_fixable": len(auto),
        "manual": len(manual),
        "applied": applied,
    }


def op_compare(
    *,
    a: Optional[str] = None,
    b: Optional[str] = None,
    vs: Optional[str] = None,
    fetch: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    git = _git()
    repo = _enter(cwd)
    if fetch:
        git.run(["fetch", "origin"], cwd=repo.bare)
    if vs:
        ref_label, rows = core_compare.compare_all_vs(git, repo, vs)
        return {"vs": ref_label, "rows": rows}
    if not a:
        raise UsageError("Specify 'a' (the worktree/branch to compare).")
    return core_compare.compare_one(git, repo, a, b)


def op_config_show(*, cwd: Optional[str] = None) -> dict:
    repo = _enter(cwd)
    pol = core_config.effective_policy()
    return {"repo": repo.name, "root": str(repo.root), "origin": _origin(repo), **pol}


def op_config_set_ssh_alias(*, value: str, cwd: Optional[str] = None) -> dict:
    git = _git()
    repo = _enter(cwd)
    origin = _origin(repo)
    if value.lower() in ("none", "-", ""):
        new_url = origin
        if origin:
            host = sshalias.url_host(origin)
            if host:
                cfg, err = sshcheck._ssh_g(host)
                real = cfg.get("hostname") if not err else None
                if real:
                    new_url = sshalias.rewrite_host(origin, real)
        core_config.SSH_ALIAS = ""
    else:
        if origin is None:
            raise UsageError("There is no origin in this repo.")
        new_url = sshalias.rewrite_host(origin, value)
        core_config.SSH_ALIAS = value

    if origin and new_url != origin:
        git.run(["remote", "set-url", "origin", new_url], cwd=repo.bare)
    core_config.write_repo_config(repo.bare, core_config.effective_policy())
    return {"ssh_alias": core_config.SSH_ALIAS, "origin": new_url}


def _ssh_report_to_dict(rep) -> dict:
    return {
        "target": rep.target,
        "hostname": rep.hostname,
        "user": rep.user,
        "identities_only": rep.identities_only,
        "config_present": rep.config_present,
        "identities": [
            {"path": i.path, "exists": i.exists, "perms_ok": i.perms_ok, "loaded": i.loaded}
            for i in rep.identities
        ],
        "agent_running": rep.agent_running,
        "agent_keys": len(rep.agent_keys),
        "live": ({"ok": rep.live.ok, "message": rep.live.message} if rep.live else None),
        "error": rep.error,
    }


def op_ssh_check(
    *,
    target: Optional[str] = None,
    all: bool = False,
    live: bool = False,
    cwd: Optional[str] = None,
) -> dict:
    if all:
        hosts = sshcheck.list_config_hosts() or list(core_config.KNOWN_GIT_HOSTS)
        reports = [sshcheck.check_host(h, live=live) for h in hosts]
    else:
        host = None
        if target:
            host = sshcheck.host_from_url(target) or target
        else:
            try:
                repo = _enter(cwd)
                url = _origin(repo)
            except Exception:
                url = None
            host = sshcheck.host_from_url(url) if url else None
            if not host:
                raise UsageError("No SSH origin here; pass 'target' (URL or host) or set all=true.")
        reports = [sshcheck.check_host(host, live=live)]
    return {"hosts": [_ssh_report_to_dict(r) for r in reports]}


# --------------------------------------------------------------------------- #
# SSH account provisioning (machine-level; no repo context). See spec §14.
# --------------------------------------------------------------------------- #

def op_ssh_add(
    name: str,
    *,
    host: str,
    email: Optional[str] = None,
    scope_dir: Optional[str] = None,
    key: Optional[str] = None,
    no_identity: bool = False,
    no_agent: bool = False,
    no_passphrase: bool = True,
    dry_run: bool = False,
) -> dict:
    # No TTY in the MCP transport → the key is generated without a passphrase by
    # default. The public key is returned for the agent to upload via its own
    # hosting connector (grove never goes to the network).
    spec = sshprov.AddSpec(
        name=name, host=host, email=email,
        scope_dir=Path(scope_dir) if scope_dir else None,
        key=Path(key) if key else None,
        no_identity=no_identity, no_agent=no_agent,
        no_passphrase=no_passphrase, dry_run=dry_run,
    )
    return sshprov.add_account(spec)


def op_ssh_accounts() -> dict:
    inv = sshprov.read_inventory()
    return {
        "accounts": [
            {
                "name": a.name, "host": a.host, "key": a.key,
                "zone": (z.scope_dir if (z := inv.zone_of(a)) else None),
                "email": (z.email if z else None),
                "routing": inv.routing_state(a),
            }
            for a in inv.accounts
        ],
        "zones": [
            {"scope_dir": z.scope_dir, "email": z.email,
             "identity_path": z.identity_path, "rewrites": z.rewrites}
            for z in inv.zones
        ],
    }


def op_ssh_doctor(*, fix: bool = False) -> dict:
    findings = sshdoctor.diagnose()
    auto = [f for f in findings if f.severity == "fix"]
    review = [f for f in findings if f.severity == "review"]
    applied = sshdoctor.apply_fixes(findings) if (fix and auto) else 0
    return {
        "findings": [
            {"check": f.check, "severity": f.severity, "target": f.target,
             "message": f.message, "fixable": f.fixer is not None}
            for f in findings
        ],
        "auto_fixable": len(auto), "review": len(review), "applied": applied,
    }


def op_ssh_remove(
    name: str,
    *,
    delete_key: bool = False,
    keep_routing: bool = False,
    confirm: bool = False,
    dry_run: bool = False,
) -> dict:
    if not confirm and not dry_run:
        raise UsageError(
            "ssh_remove edits ~/.ssh/config and ~/.gitconfig; set confirm=true (or dry_run=true)."
        )
    return sshprov.remove_account(name, delete_key=delete_key,
                                  keep_routing=keep_routing, dry_run=dry_run)
