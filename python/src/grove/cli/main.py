"""Entry point of the `gwt` CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from ..core import config as core_config
from ..core import setup as core_setup
from ..core.errors import WtError, UsageError
from ..core.gitrunner import GitRunner
from ..core.model import Worktree, list_worktrees
from ..core.repo import find_repo, RepoContext
from .output import Output


def _enter_repo(args) -> RepoContext:
    """Locates the managed repo and loads its policy (grove.toml)."""
    repo = find_repo(_base_dir(args))
    core_config.load(repo.bare)
    return repo


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_runner(args, out: Output) -> GitRunner:
    confirm = out.confirm_git if getattr(args, "confirm_each", False) else None
    return GitRunner(
        on_command=out.git_echo,
        confirm=confirm,
        dry_run=getattr(args, "dry_run", False),
    )


def _base_dir(args) -> Path:
    return Path(args.C).resolve() if getattr(args, "C", None) else Path.cwd()


def _truncate(s: str, width: int) -> str:
    return s if len(s) <= width else s[: width - 1] + "…"


def _status_str(wt: Worktree) -> str:
    if wt.is_bare:
        return "(bare)"
    if not wt.exists:
        return "missing"
    if wt.upstream is None:
        clean = "dirty" if wt.dirty else "clean"
        return f"no-upstream {clean}"
    clean = "dirty" if wt.dirty else "clean"
    return f"↑{wt.ahead or 0} ↓{wt.behind or 0} {clean}"


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def _resolve_setup_url(args, out: Output) -> str:
    """Decides the final clone URL, choosing a local SSH alias if applicable."""
    from ..core import sshalias

    url = args.url
    host = sshalias.url_host(url)
    if not host:
        return url  # not SSH (e.g. https): no alias

    matches = sshalias.matching_aliases(host, out.git_echo)

    # 1) Explicit flag.
    if getattr(args, "ssh_alias", None):
        chosen = args.ssh_alias
        if chosen.lower() in ("none", "-"):
            return url
        known = {m.alias for m in matches}
        if chosen not in known and chosen not in sshalias.list_config_hosts():
            out.warn(f"Alias '{chosen}' is not in ~/.ssh/config; using it anyway.")
        new = sshalias.rewrite_host(url, chosen)
        core_config.SSH_ALIAS = chosen
        out.step(f"Using SSH alias '{chosen}' → {new}")
        return new

    if not matches:
        return url

    # 2) Interactive: ask.
    if sys.stdin.isatty() and not out.json_mode:
        out.plain(f"SSH aliases detected for {host}:")
        for i, m in enumerate(matches, 1):
            keys = ", ".join(m.identity_files) or "(no IdentityFile)"
            out.plain(f"  {i}) {m.alias}   {keys}")
        out.plain("  0) use the URL as-is (no alias)")
        try:
            ans = input("Which one to use? [0] ").strip()
        except EOFError:
            ans = ""
        if ans.isdigit() and 1 <= int(ans) <= len(matches):
            chosen = matches[int(ans) - 1].alias
            new = sshalias.rewrite_host(url, chosen)
            core_config.SSH_ALIAS = chosen
            out.step(f"Using SSH alias '{chosen}' → {new}")
            return new
        return url

    # 3) Non-interactive without flag: use as-is, but warn.
    nombres = ", ".join(m.alias for m in matches)
    out.step(f"Notice: there are SSH aliases for {host} ({nombres}). Using the URL as-is; "
             f"use --ssh-alias <alias> to choose.")
    return url


def cmd_setup(args, out: Output) -> int:
    git = _make_runner(args, out)
    into = Path(args.into).resolve() if args.into else _base_dir(args)

    # Resolve and apply the profile policy (if specified) before creating.
    profile_name = args.profile or core_config.DEFAULT_PROFILE
    try:
        policy = core_config.resolve_profile(profile_name)
    except KeyError:
        raise UsageError(f"Unknown profile: '{profile_name}'.")
    core_config.apply_policy(policy)
    out.step(f"Profile: {profile_name} (base {core_config.DEFAULT_BASE}, tickets {core_config.TICKETS})")

    url = _resolve_setup_url(args, out)

    ctx = core_setup.setup(
        git,
        url,
        into=into,
        name=args.name,
        base_branch=core_config.DEFAULT_BASE,
        step=out.step,
    )
    cfg_path = core_config.write_repo_config(ctx.bare, core_config.effective_policy())
    out.set_result({"name": ctx.name, "root": str(ctx.root), "profile": profile_name,
                    "base": core_config.DEFAULT_BASE})
    out.success(f"Repo {ctx.name} ready")
    if not out.quiet:
        out.plain(f"  .bare/       bare repository (+ {cfg_path.name})")
        out.plain(f"  {core_config.DEFAULT_BASE}/  [tracks origin/{core_config.DEFAULT_BASE}]")
    return 0


def cmd_list(args, out: Output) -> int:
    git = _make_runner(args, out)
    repo = _enter_repo(args)
    wts = list_worktrees(git, repo, with_status=True)

    # Filters.
    def keep(wt: Worktree) -> bool:
        if args.orphans and not (wt.prunable or not wt.exists):
            return False
        if args.dirty and not wt.dirty:
            return False
        if args.type:
            cls = wt.classification
            kind = cls.kind if cls else None
            typ = cls.type if cls else None
            if args.type not in (kind, typ):
                return False
        return True

    rows = [wt for wt in wts if keep(wt)]

    if out.json_mode:
        out.set_result([
            {
                "path": str(wt.path),
                "rel_path": wt.rel_path,
                "branch": wt.branch,
                "bare": wt.is_bare,
                "detached": wt.is_detached,
                "prunable": wt.prunable,
                "exists": wt.exists,
                "ticket": (wt.classification.ticket if wt.classification else None),
                "kind": (wt.classification.kind if wt.classification else None),
                "type": (wt.classification.type if wt.classification else None),
                "dirty": wt.dirty,
                "ahead": wt.ahead,
                "behind": wt.behind,
                "upstream": wt.upstream,
            }
            for wt in rows
        ])
        out.success(f"{len(rows)} worktree(s)")
        return 0

    if not rows:
        out.plain("(no worktrees)")
        return 0

    # Table.
    PATHW, BRANCHW = 45, 45
    headers = ("FOLDER", "BRANCH", "TICKET", "STATUS")
    table = []
    for wt in rows:
        carpeta = "(bare)" if wt.is_bare else wt.rel_path
        rama = wt.branch or ("(detached)" if wt.is_detached else "—")
        ticket = (wt.classification.ticket if wt.classification and wt.classification.ticket else "—")
        table.append((
            _truncate(carpeta, PATHW),
            _truncate(rama, BRANCHW),
            ticket,
            _status_str(wt),
        ))

    w0 = max(len(headers[0]), *(len(r[0]) for r in table))
    w1 = max(len(headers[1]), *(len(r[1]) for r in table))
    w2 = max(len(headers[2]), *(len(r[2]) for r in table))
    fmt = f"{{:<{w0}}}  {{:<{w1}}}  {{:<{w2}}}  {{}}"
    out.plain(fmt.format(*headers))
    for r in table:
        out.plain(fmt.format(*r))
    return 0


def _finish_create(args, out: Output, repo, path) -> int:
    rel = None
    try:
        rel = str(Path(path).relative_to(repo.root)).replace("\\", "/")
    except (ValueError, AttributeError):
        rel = str(path)
    out.set_result({"path": str(path), "rel_path": rel, "branch": rel})
    if getattr(args, "print_path", False) and not out.json_mode:
        # Only the path on stdout, for `cd "$(gwt create ... --print-path)"`.
        print(str(path))
        return 0
    out.success(f"Worktree created: {path}")
    return 0


def cmd_create(args, out: Output) -> int:
    from ..core import create as core_create

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    params = args.params
    kind = params[0]

    if kind == "release":
        if len(params) < 2:
            raise UsageError("Usage: gwt create release <version> [--base <branch>]")
        path = core_create.create_release(
            git, repo, version=params[1], base=args.base, step=out.step
        )
    elif kind == "temp":
        if len(params) < 2:
            raise UsageError("Usage: gwt create temp <name>")
        path = core_create.create_temp(git, repo, name=params[1], step=out.step)
    else:
        ticket, type_, desc = _parse_ticket_form(params)
        path = core_create.create_ticket(
            git, repo,
            type=type_, name=desc, ticket=ticket,
            base=args.base, step=out.step,
        )
    return _finish_create(args, out, repo, path)


def _parse_ticket_form(params):
    """Interprets the 'create' args according to the repo's ticket policy.

    required: <TICKET> <type> "<desc>"
    off:      <type> "<desc>"
    optional: detects whether the first arg is a ticket key.
    """
    mode = core_config.TICKETS
    has_ticket = bool(params) and core_config.TICKET_RE.fullmatch(params[0]) is not None

    if mode == "off" or (mode == "optional" and not has_ticket):
        if len(params) < 2:
            raise UsageError('Usage (without ticket): gwt create <type> "<name>"')
        return None, params[0], params[1]

    # required, or optional with a detected key.
    if len(params) < 3:
        raise UsageError('Usage: gwt create <TICKET-ID> <type> "<name>"')
    return params[0], params[1], params[2]


def cmd_track(args, out: Output) -> int:
    from ..core import track as core_track

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    path = core_track.track(
        git, repo, branch=args.origin_branch, as_=args.as_, step=out.step, warn=out.warn
    )
    out.set_result({"path": str(path), "branch": args.origin_branch})
    out.success(f"Branch brought in: {path}")
    return 0


def cmd_doctor(args, out: Output) -> int:
    from ..core import doctor as core_doctor

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    issues = core_doctor.diagnose(git, repo)
    auto = [i for i in issues if i.fix is not None]
    manual = [i for i in issues if i.fix is None]

    if out.json_mode:
        applied = 0
        if args.fix and auto:
            applied = core_doctor.apply(issues)
        out.set_result({
            "issues": [
                {"kind": i.kind, "severity": i.severity, "target": i.target,
                 "message": i.message, "action": i.action, "fixable": i.fix is not None}
                for i in issues
            ],
            "auto_fixable": len(auto),
            "manual": len(manual),
            "applied": applied,
        })
        out.success(
            f"{len(issues)} problem(s); {len(auto)} auto-fixable, {len(manual)} manual"
            + (f"; {applied} applied" if args.fix else "")
        )
        return 0

    if not issues:
        out.success("No problems: all worktrees follow the convention.")
        return 0

    out.plain(f"Problems found in {repo.name}:")
    for i in issues:
        mark = out._c("✗", "red") if i.fix is not None else out._c("!", "yellow")
        out.plain(f"  {mark} {i.kind:<14} {i.target}")
        out.plain(f"      {i.message}  ->  {i.action}")
    out.plain(f"{len(auto)} auto-fixable · {len(manual)} require manual review.")

    if args.dry_run or not auto:
        if not auto and manual:
            out.plain("(nothing to fix automatically)")
        return 0

    do_fix = args.fix
    if not do_fix:
        try:
            ans = input(f"Apply the {len(auto)} automatic fixes? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        do_fix = ans in ("y", "yes")

    if do_fix:
        n = core_doctor.apply(issues)
        out.success(f"{n} fix(es) applied.")
    else:
        out.plain("No changes were applied.")
    return 0


def cmd_remove(args, out: Output) -> int:
    from ..core import remove as core_remove

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    suffix = " (dry-run)" if getattr(args, "dry_run", False) else ""

    if args.merged:
        removed = core_remove.sweep_merged(
            git, repo, delete_branch=args.delete_branch, force=args.force, step=out.step
        )
        out.set_result({"mode": "merged", "removed": [w.rel_path for w in removed],
                        "dry_run": getattr(args, "dry_run", False)})
        if not removed:
            out.success("There are no ticket worktrees merged into the base to remove.")
        else:
            out.success(f"{len(removed)} worktree(s) removed{suffix}: "
                        + ", ".join(w.rel_path for w in removed))
        return 0

    if not args.target:
        raise UsageError("Specify a target (ticket, branch or path) or use --merged.")

    wt = core_remove.resolve_target(git, repo, args.target)
    core_remove.remove_one(
        git, repo, wt, delete_branch=args.delete_branch, force=args.force, step=out.step
    )
    out.set_result({"mode": "single", "removed": [wt.rel_path],
                    "delete_branch": args.delete_branch,
                    "dry_run": getattr(args, "dry_run", False)})
    out.success(f"Worktree removed{suffix}: {wt.rel_path}")
    return 0


def cmd_sync(args, out: Output) -> int:
    from ..core import sync as core_sync
    from ..core.model import list_worktrees as _lw

    git = _make_runner(args, out)
    repo = _enter_repo(args)

    # Resolve target (with status, to warn about losses).
    if args.target:
        from ..core import remove as core_remove
        wt = core_remove.resolve_target(git, repo, args.target)
    else:
        cwd = Path.cwd().resolve()
        wt = None
        for w in _lw(git, repo, with_status=True):
            if w.is_bare:
                continue
            try:
                cwd.relative_to(w.path.resolve())
                wt = w
                break
            except ValueError:
                continue
        if wt is None:
            raise UsageError("Specify the worktree to sync (not detected from the current directory).")

    # Destructive warning.
    losses = []
    if wt.ahead:
        losses.append(f"{wt.ahead} local commit(s) not pushed")
    if wt.dirty:
        losses.append("uncommitted changes")
    if losses and not args.yes and not getattr(args, "dry_run", False):
        if out.json_mode:
            raise UsageError(
                f"sync would discard in {wt.rel_path}: {', '.join(losses)}. "
                f"In --json mode use --yes to confirm."
            )
        out.warn(f"sync will discard in {wt.rel_path}: {', '.join(losses)}.")
        try:
            ans = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            out.plain("Cancelled.")
            return 0

    core_sync.sync_worktree(git, repo, wt, clean=args.clean, step=out.step)
    suffix = " (dry-run)" if getattr(args, "dry_run", False) else ""
    out.set_result({"worktree": wt.rel_path, "discarded": losses,
                    "dry_run": getattr(args, "dry_run", False)})
    out.success(f"Worktree synced{suffix}: {wt.rel_path}")
    return 0


def cmd_publish(args, out: Output) -> int:
    from ..core import publish as core_publish

    git = _make_runner(args, out)
    repo = _enter_repo(args)

    integration = args.into or core_config.INTEGRATION_BRANCH
    if not integration:
        raise UsageError("No integration branch configured. Use --into <branch>.")

    branches = [core_publish.resolve_branch(git, repo, t) for t in args.targets]
    int_path = core_publish.ensure_integration(git, repo, integration, step=out.step)
    suffix = " (dry-run)" if getattr(args, "dry_run", False) else ""

    mode = "regenerate" if args.regenerate else "additive"
    if args.regenerate:
        base = args.base or core_config.DEFAULT_BASE
        if not args.yes and not getattr(args, "dry_run", False):
            if out.json_mode:
                raise UsageError(
                    f"--regenerate will force-push to origin/{integration}. "
                    f"In --json mode use --yes to confirm."
                )
            out.warn(f"--regenerate will rewrite origin/{integration} with a force-push "
                     f"(from {base} + {len(branches)} branch/es).")
            try:
                ans = input("Continue? [y/N] ").strip().lower()
            except EOFError:
                ans = ""
            if ans not in ("y", "yes"):
                out.plain("Cancelled.")
                return 0
        core_publish.publish_regenerate(
            git, repo, integration, int_path, branches, base=base, step=out.step
        )
    else:
        core_publish.publish_additive(
            git, repo, integration, int_path, branches, no_sync=args.no_sync, step=out.step
        )

    out.set_result({"integration": integration, "mode": mode, "branches": branches,
                    "dry_run": getattr(args, "dry_run", False)})
    out.success(f"Published{suffix} to {integration}: {', '.join(branches)}")
    return 0


def _origin_url(args) -> Optional[str]:
    """Origin URL of the current repo, or None if there is no managed repo."""
    try:
        repo = find_repo(_base_dir(args))
    except WtError:
        return None
    git = GitRunner()
    res = git.run(["remote", "get-url", "origin"], cwd=repo.bare, check=False, mutating=False)
    return res.stdout.strip() if res.returncode == 0 else None


def _render_ssh_report(out: Output, rep) -> None:
    if rep.error:
        out.error(f"{rep.target}: {rep.error}")
        return
    out.plain(f"Host: {out._c(rep.target, 'dim')}")
    out.plain(f"  HostName: {rep.hostname or '—'}   User: {rep.user or '—'}"
              f"   IdentitiesOnly: {'yes' if rep.identities_only else 'no'}")

    if not rep.config_present:
        out.plain(f"  {out._c('!', 'yellow')} no ~/.ssh/config: ssh will use default "
                  f"keys or the agent")

    # (a) Show only keys that exist; summarize the rest in a note.
    existing = [i for i in rep.identities if i.exists]
    for idn in existing:
        bits = []
        if idn.perms_ok is False:
            bits.append(out._c("open permissions (use chmod 600)", "yellow"))
        elif idn.perms_ok is True:
            bits.append("permissions ✓")
        else:
            bits.append("permissions N/A")
        if idn.loaded is True:
            bits.append("loaded in agent ✓")
        elif idn.loaded is False:
            bits.append(out._c("not loaded in agent", "yellow"))
        mark = "✓" if (idn.perms_ok is not False) else "!"
        color = "green" if mark == "✓" else "yellow"
        out.plain(f"  {out._c(mark, color)} key {idn.path} — {' · '.join(bits)}")

    if not existing:
        if rep.agent_running and rep.agent_keys:
            out.plain(f"  {out._c('✓', 'green')} no key on disk, but the agent has "
                      f"{len(rep.agent_keys)} key(s) — can authenticate")
        else:
            out.plain(f"  {out._c('!', 'yellow')} no usable key (neither in ~/.ssh nor in the "
                      f"agent); use --live to test or generate/load a key")
    else:
        if not rep.agent_running:
            out.plain(f"  {out._c('!', 'yellow')} ssh-agent not available")
        else:
            out.plain(f"  agent: {len(rep.agent_keys)} key(s) loaded")

    if rep.live is not None:
        mark = out._c("✓", "green") if rep.live.ok else out._c("✗", "red")
        out.plain(f"  {mark} authentication: {rep.live.message}")
    elif not rep.config_present:
        out.plain(f"  {out._c('→', 'dim')} tip: add --live to test real authentication")


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


def cmd_ssh_check(args, out: Output) -> int:
    from ..core import sshcheck

    echo = out.git_echo
    reports = []
    local_keys = None

    if args.all:
        hosts = sshcheck.list_config_hosts()
        if hosts:
            reports = [sshcheck.check_host(h, live=args.live, echo=echo) for h in hosts]
        else:
            local_keys = sshcheck.list_local_keys(echo)
            reports = [sshcheck.check_host(h, live=args.live, echo=echo)
                       for h in core_config.KNOWN_GIT_HOSTS]
    else:
        target = args.target
        if target:
            target = sshcheck.host_from_url(target) or target
        else:
            url = _origin_url(args)
            if not url:
                raise UsageError("No repo/origin here. Pass a URL or host, or use --all.")
            host = sshcheck.host_from_url(url)
            if not host:
                raise UsageError(f"The origin is not SSH ({url}); nothing to diagnose.")
            target = host
        reports = [sshcheck.check_host(target, live=args.live, echo=echo)]

    if out.json_mode:
        out.set_result({
            "hosts": [_ssh_report_to_dict(r) for r in reports],
            "local_keys": ([
                {"path": k.path, "exists": k.exists, "perms_ok": k.perms_ok, "loaded": k.loaded}
                for k in local_keys
            ] if local_keys is not None else None),
        })
        out.success(f"{len(reports)} host(s) diagnosed")
        return 0

    # Human render.
    if local_keys is not None:
        out.warn("No ~/.ssh/config (or it declares no Hosts). Showing an alternative overview:")
        out.plain("")
        out.plain("Keys in ~/.ssh:")
        if not local_keys:
            out.plain(f"  {out._c('!', 'yellow')} no private keys found in ~/.ssh")
        for idn in local_keys:
            bits = []
            if idn.perms_ok is False:
                bits.append(out._c("open permissions (use chmod 600)", "yellow"))
            elif idn.perms_ok is True:
                bits.append("permissions ✓")
            if idn.loaded is True:
                bits.append("loaded in agent ✓")
            elif idn.loaded is False:
                bits.append(out._c("not loaded in agent", "yellow"))
            out.plain(f"  {out._c('•', 'dim')} {idn.path} — {' · '.join(bits) or 'ok'}")
    for i, rep in enumerate(reports):
        if i or local_keys is not None:
            out.plain("")
        _render_ssh_report(out, rep)
    return 0


def cmd_ssh_help(args, out: Output) -> int:
    out.plain("Usage: gwt ssh check [<url-or-host>] [--all] [--live]")
    return 0


def _origin_of(repo) -> Optional[str]:
    git = GitRunner()
    res = git.run(["remote", "get-url", "origin"], cwd=repo.bare, check=False, mutating=False)
    return res.stdout.strip() if res.returncode == 0 else None


def _cwd_branch(git, repo):
    """Branch of the worktree containing the current directory, or None."""
    from ..core.model import list_worktrees as _lw
    cwd = Path.cwd().resolve()
    for w in _lw(git, repo, with_status=False):
        if w.is_bare or not w.branch:
            continue
        try:
            cwd.relative_to(w.path.resolve())
            return w.branch
        except ValueError:
            continue
    return None


def cmd_compare(args, out: Output) -> int:
    from ..core import compare as core_compare

    git = _make_runner(args, out)
    repo = _enter_repo(args)

    if args.fetch:
        out.step("Updating from origin (fetch)")
        git.run(["fetch", "origin"], cwd=repo.bare)

    if args.vs:
        ref_label, rows = core_compare.compare_all_vs(git, repo, args.vs)
        if out.json_mode:
            out.set_result({"vs": ref_label, "rows": rows})
            out.success(f"{len(rows)} worktree(s) compared against {ref_label}")
            return 0
        out.plain(f"Worktrees vs {ref_label}:")
        if not rows:
            out.plain("  (no worktrees)")
            return 0
        w0 = max(len("WORKTREE"), *(len(r["a"]) for r in rows))
        out.plain(f"  {'WORKTREE':<{w0}}   STATUS")
        for r in rows:
            out.plain(f"  {r['a']:<{w0}}   ↑{r['ahead']} ↓{r['behind']}  {r['status']}")
        return 0

    cwd_branch = None if args.a else _cwd_branch(git, repo)
    res = core_compare.compare_one(git, repo, args.a, args.b, cwd_branch=cwd_branch)
    if out.json_mode:
        out.set_result(res)
        out.success(f"{res['a']} vs {res['b']}: ↑{res['ahead']} ↓{res['behind']} ({res['status']})")
        return 0
    out.plain(f"{res['a']}  ↑{res['ahead']} ↓{res['behind']}  "
              f"({res['status']} relative to {res['b']})")
    return 0


def _worktree_target(args, git, repo):
    """Returns the target Worktree: args.target's, or the current directory's."""
    from ..core.model import list_worktrees as _lw
    if getattr(args, "target", None):
        from ..core import remove as core_remove
        return core_remove.resolve_target(git, repo, args.target)
    cwd = Path.cwd().resolve()
    for w in _lw(git, repo, with_status=False):
        if w.is_bare or not w.branch:
            continue
        try:
            cwd.relative_to(w.path.resolve())
            return w
        except ValueError:
            continue
    raise UsageError("Specify the worktree (not detected from the current directory).")


def cmd_patch(args, out: Output) -> int:
    from ..core import patch as core_patch

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    wt = _worktree_target(args, git, repo)
    base = args.base or core_config.DEFAULT_BASE

    patches_dir = None
    if core_config.ARTIFACTS_DIR:
        patches_dir = repo.root / core_config.ARTIFACTS_DIR / core_patch.PATCHES_SUBDIR

    res = core_patch.generate(
        git, repo, wt,
        base=base, wip=args.wip, fmt_patch=args.format_patch,
        patches_dir=patches_dir,
        out_path=(Path(args.output) if args.output else None),
        to_stdout=args.stdout, step=out.step,
    )

    # stdout output: the raw patch (or, in JSON, inside result).
    if args.stdout:
        if out.json_mode:
            out.set_result({"mode": res["mode"], "content": res.get("stdout", ""),
                            "empty": res["empty"]})
            out.success("patch on stdout")
        else:
            print(res.get("stdout", ""), end="")
        return 0

    out.set_result({k: v for k, v in res.items() if k != "stdout"})
    if res["empty"]:
        out.warn("The patch is empty: no differences from the base"
                 + (" (did you use --wip with no uncommitted changes?)" if args.wip else "") + ".")
    if res["mode"] == "format-patch":
        out.success(f"{len(res.get('files', []))} patch(es) in {res['path']}")
    else:
        out.success(f"Patch generated: {res['path']}")
    return 0


def cmd_artifacts(args, out: Output) -> int:
    """Prints (and creates) the path of the local artifacts folder."""
    from ..core import naming
    repo = _enter_repo(args)
    if not core_config.ARTIFACTS_DIR:
        raise UsageError("The artifacts folder is disabled (artifacts_dir empty).")

    path = repo.root / core_config.ARTIFACTS_DIR
    if args.target:
        # Subfolder: if the arg is a worktree, use its path; otherwise a slug of the arg.
        sub = None
        try:
            from ..core import remove as core_remove
            wt = core_remove.resolve_target(GitRunner(), repo, args.target)
            sub = wt.rel_path.replace("/", "-")
        except WtError:
            sub = naming.slugify(args.target)
        path = path / sub

    path.mkdir(parents=True, exist_ok=True)
    out.set_result({"path": str(path)})
    if out.json_mode:
        out.success(f"artifacts: {path}")
    else:
        print(str(path))   # bare path, for cd "$(gwt artifacts)"
    return 0


def cmd_config(args, out: Output) -> int:
    repo = _enter_repo(args)
    origin = _origin_of(repo)

    if args.config_command == "set-ssh-alias":
        from ..core import sshalias, sshcheck
        git = _make_runner(args, out)
        value = args.value
        if value.lower() in ("none", "-", ""):
            host = sshalias.url_host(origin) if origin else None
            new_url = origin
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
            out.step(f"Rewriting origin → {new_url}")
            git.run(["remote", "set-url", "origin", new_url], cwd=repo.bare)
        core_config.write_repo_config(repo.bare, core_config.effective_policy())
        out.set_result({"ssh_alias": core_config.SSH_ALIAS, "origin": new_url})
        out.success(f"ssh_alias = '{core_config.SSH_ALIAS or '(none)'}' · origin = {new_url}")
        return 0

    # show
    pol = core_config.effective_policy()
    report = {"repo": repo.name, "root": str(repo.root), "origin": origin, **pol}
    out.set_result(report)
    if not out.json_mode:
        out.plain(f"Repo: {repo.name}")
        out.plain(f"  origin: {origin or '—'}")
        for k in ("default_base", "tickets", "ssh_alias", "integration_branch"):
            out.plain(f"  {k}: {pol.get(k)}")
        out.plain(f"  allowed_types: {', '.join(pol.get('allowed_types', []))}")
        out.plain(f"  special_worktrees: {', '.join(pol.get('special_worktrees', []))}")
        out.plain("  (use --json for the full detail)")
    else:
        out.success(f"Config for {repo.name}")
    return 0


def _not_implemented(name):
    def _fn(args, out: Output) -> int:
        out.warn(f"'{name}' is not implemented yet in this prototype.")
        return 0
    return _fn


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    parser.add_argument("-v", "--verbose", action="store_true", help="print each git command")
    parser.add_argument("--confirm-each", dest="confirm_each", action="store_true",
                        help="ask for confirmation before each git command (implies -v)")
    parser.add_argument("--no-color", dest="no_color", action="store_true", help="no colors")
    parser.add_argument("--json", action="store_true",
                        help="JSON output with status, reason and result data")
    parser.add_argument("-C", metavar="PATH", help="run as if the cwd were PATH")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gwt", description="grove — git worktree management with a convention.")
    p.add_argument("--version", action="store_true", help="show the version and exit")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("setup", help="initialize a repo (bare + base worktree)")
    _common(sp)
    sp.add_argument("url", help="origin URL")
    sp.add_argument("--name", help="repo folder name")
    sp.add_argument("--into", help="where to create the repo folder (default: cwd)")
    sp.add_argument("--profile", help="policy profile to apply (default: default)")
    sp.add_argument("--ssh-alias", dest="ssh_alias", metavar="ALIAS",
                    help="~/.ssh/config alias to use for the remote (or 'none' for the URL as-is)")
    sp.set_defaults(func=cmd_setup)

    lp = sub.add_parser("list", help="list the repo's worktrees")
    _common(lp)
    lp.add_argument("--type", help="filter by type/kind")
    lp.add_argument("--dirty", action="store_true", help="only worktrees with changes")
    lp.add_argument("--orphans", action="store_true", help="only orphan/prunable")
    lp.set_defaults(func=cmd_list)

    cp = sub.add_parser(
        "create",
        help="create a ticket / release / temp worktree",
        description=(
            'gwt create <TICKET-ID> <feature|hotfix|bugfix> "<name>"\n'
            "gwt create release <version>\n"
            "gwt create temp <name>"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _common(cp)
    cp.add_argument("params", nargs="+", help="arguments per the subform (see description)")
    cp.add_argument("--base", help="base branch (default: the repo's)")
    cp.add_argument("--print-path", dest="print_path", action="store_true",
                    help="print only the created path")
    cp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    cp.set_defaults(func=cmd_create)

    tp = sub.add_parser("track", help="bring an existing branch (local or from origin) into the structure")
    _common(tp)
    tp.add_argument("origin_branch", metavar="branch",
                    help="branch name (local or from origin)")
    tp.add_argument("--as", dest="as_", metavar="TYPE/TICKET-XXXXX-slug",
                    help="explicit destination to relocate or force a type")
    tp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    tp.set_defaults(func=cmd_track)

    dp = sub.add_parser("doctor", help="detect and fix hygiene problems")
    _common(dp)
    dp.add_argument("--fix", action="store_true", help="apply the fixes without asking")
    dp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="report only, do not modify")
    dp.set_defaults(func=cmd_doctor)

    rp = sub.add_parser("remove", aliases=["rm"], help="remove a worktree safely")
    _common(rp)
    rp.add_argument("target", nargs="?", help="ticket, branch or path of the worktree")
    rp.add_argument("--delete-branch", dest="delete_branch", action="store_true",
                    help="also delete the local branch (if merged/pushed)")
    rp.add_argument("--force", action="store_true",
                    help="remove even if dirty; delete the branch even if not merged")
    rp.add_argument("--merged", action="store_true",
                    help="sweep all ticket worktrees merged into the base")
    rp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    rp.set_defaults(func=cmd_remove)

    pp = sub.add_parser("publish", help="bring branches into the shared integration branch")
    _common(pp)
    pp.add_argument("targets", nargs="+", help="tickets or branches to publish")
    pp.add_argument("--into", help="integration branch (default: config integration_branch)")
    pp.add_argument("--regenerate", action="store_true",
                    help="regenerate the integration branch from the base (force-push)")
    pp.add_argument("--base", help="base for --regenerate (default: repo base branch)")
    pp.add_argument("--no-sync", dest="no_sync", action="store_true",
                    help="additive mode: do not sync the integration branch before merging")
    pp.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    pp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    pp.set_defaults(func=cmd_publish)

    syp = sub.add_parser("sync", help="re-sync a worktree with the origin (reset --hard)")
    _common(syp)
    syp.add_argument("target", nargs="?", help="ticket, branch or path (default: current worktree)")
    syp.add_argument("--clean", action="store_true", help="also delete untracked files")
    syp.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    syp.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="show what it would do without executing")
    syp.set_defaults(func=cmd_sync)

    mp = sub.add_parser("compare", help="sync status between branches/worktrees (read-only)")
    _common(mp)
    mp.add_argument("a", nargs="?", help="worktree/branch A (default: current worktree)")
    mp.add_argument("b", nargs="?", help="worktree/branch B (default: upstream of A)")
    mp.add_argument("--vs", metavar="REF", help="compare ALL worktrees against REF")
    mp.add_argument("--fetch", action="store_true", help="git fetch before comparing")
    mp.set_defaults(func=cmd_compare)

    pat = sub.add_parser("patch", help="generate a patch of the worktree (diff vs base or format-patch)")
    _common(pat)
    pat.add_argument("target", nargs="?", help="worktree (default: the current one)")
    pat.add_argument("--base", help="comparison base (default: repo base branch)")
    pat.add_argument("--format-patch", dest="format_patch", action="store_true",
                     help="one .patch per commit (applyable with git am)")
    pat.add_argument("--wip", action="store_true",
                     help="include uncommitted changes (working tree vs HEAD)")
    pat.add_argument("--output", "-o", help="output path (file for diff, folder for format-patch)")
    pat.add_argument("--stdout", action="store_true",
                     help="print the patch to stdout instead of writing a file")
    pat.set_defaults(func=cmd_patch)

    ap = sub.add_parser("artifacts", help="path of the local artifacts folder (creates it if missing)")
    _common(ap)
    ap.add_argument("target", nargs="?", help="worktree or name for a subfolder (optional)")
    ap.set_defaults(func=cmd_artifacts)

    cfgp = sub.add_parser("config", help="show or adjust the repo configuration")
    cfgp.set_defaults(func=cmd_config, config_command="show")
    cfg_sub = cfgp.add_subparsers(dest="config_command")
    cshow = cfg_sub.add_parser("show", help="report the repo configuration")
    _common(cshow)
    cshow.set_defaults(func=cmd_config, config_command="show")
    cset = cfg_sub.add_parser("set-ssh-alias", help="set the SSH alias and rewrite the origin")
    _common(cset)
    cset.add_argument("value", help="~/.ssh/config alias (or 'none' for the canonical URL)")
    cset.set_defaults(func=cmd_config, config_command="set-ssh-alias")
    # 'gwt config' without a subcommand = show
    _common(cfgp)

    ssp = sub.add_parser("ssh", help="SSH configuration diagnostics")
    ssp.set_defaults(func=cmd_ssh_help)
    ssh_sub = ssp.add_subparsers(dest="ssh_command")
    chk = ssh_sub.add_parser("check", help="diagnose SSH for a remote")
    _common(chk)
    chk.add_argument("target", nargs="?", help="URL or host (default: repo origin)")
    chk.add_argument("--all", action="store_true", help="all Hosts in ~/.ssh/config")
    chk.add_argument("--live", action="store_true", help="authentication test (ssh -T)")
    chk.set_defaults(func=cmd_ssh_check)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "version", False):
        from .. import __version__
        print(f"grove (gwt) {__version__}")
        return 0

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    verbose = getattr(args, "verbose", False) or getattr(args, "confirm_each", False)
    json_mode = getattr(args, "json", False)
    # --print-path debe dejar solo la ruta en stdout: silencia los pasos.
    quiet = getattr(args, "quiet", False) or getattr(args, "print_path", False)
    out = Output(
        quiet=quiet,
        no_color=getattr(args, "no_color", False),
        verbose=verbose,
        json_mode=json_mode,
    )
    command = getattr(args, "command", None)

    def _emit(envelope: dict) -> None:
        print(json.dumps(envelope, indent=2, ensure_ascii=False))

    try:
        rc = args.func(args, out)
        if json_mode:
            _emit({
                "command": command,
                "status": "ok",
                "exit_code": rc,
                "message": out.message,
                "result": out.result,
                "log": out.log,
            })
        return rc
    except WtError as e:
        if json_mode:
            _emit({
                "command": command,
                "status": "error",
                "exit_code": e.exit_code,
                "error_type": type(e).__name__,
                "message": str(e),
                "log": out.log,
            })
        else:
            out.error(str(e))
        return e.exit_code
    except KeyboardInterrupt:
        if json_mode:
            _emit({"command": command, "status": "error", "exit_code": 130,
                   "error_type": "KeyboardInterrupt", "message": "Interrupted.", "log": out.log})
        else:
            out.error("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
