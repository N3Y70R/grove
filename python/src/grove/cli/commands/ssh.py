"""SSH diagnostics and multi-account provisioning: gwt ssh …"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...core import config as core_config
from ...core.errors import WtError, UsageError
from ...core.gitrunner import GitRunner
from ...core.repo import find_repo
from ..output import Output
from .._shared import _base_dir, _common, _enter_repo, _origin_of


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
    from ...core import sshcheck

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


def cmd_ssh_aliases(args, out: Output) -> int:
    """Maps a repo (or a host/URL) to the SSH aliases that could serve it."""
    from ...core import sshalias, sshcheck

    target = args.target
    if target:
        host = sshcheck.host_from_url(target) or target
    else:
        repo = _enter_repo(args)
        origin = _origin_of(repo)
        if not origin:
            raise UsageError("No repo/origin here. Pass a URL or host.")
        host = sshalias.url_host(origin)
        if not host:
            raise UsageError(f"The origin is not SSH ({origin}); no alias applies.")

    rep = sshalias.report_for_host(host, out.git_echo)

    if out.json_mode:
        out.set_result({
            "host": rep.host,
            "current": rep.current,
            "aliases": [
                {"alias": m.alias, "hostname": m.hostname, "identity_files": m.identity_files,
                 "current": m.alias == rep.current}
                for m in rep.matches
            ],
        })
        out.success(f"{len(rep.matches)} alias(es) for {rep.host}")
        return 0

    out.plain(f"SSH aliases for {rep.host}:")
    if not rep.matches:
        out.plain("  (none in ~/.ssh/config — the canonical host is used directly)")
        return 0
    for m in rep.matches:
        mark = out._c(" ← current", "green") if m.alias == rep.current else ""
        keys = ", ".join(m.identity_files) or "(no IdentityFile)"
        out.plain(f"  {out._c('•', 'dim')} {m.alias}   {keys}{mark}")
    if rep.current is None:
        out.plain("  (none applied to this origin; set one with: gwt config set-ssh-alias <alias>)")
    return 0


def cmd_ssh_add(args, out: Output) -> int:
    from ...core import sshprov

    if out.json_mode and not args.no_passphrase:
        raise UsageError("--json requires --no-passphrase (no TTY to enter a passphrase).")

    spec = sshprov.AddSpec(
        name=args.name,
        host=args.host,
        email=args.email,
        scope_dir=Path(args.scope_dir) if args.scope_dir else None,
        key=Path(args.key) if args.key else None,
        no_identity=args.no_identity,
        no_agent=args.no_agent,
        no_passphrase=args.no_passphrase,
        dry_run=args.dry_run,
    )
    git = GitRunner(dry_run=args.dry_run, on_command=out.git_echo)
    res = sshprov.add_account(spec, git, echo=out.git_echo)

    if args.print_pubkey:
        print(res["pubkey"])
        return 0

    for s in res["steps"]:
        out.step(s)
    if res["name_missing"]:
        out.warn("Global user.name is not set; set it so commits are well-formed: "
                 "git config --global user.name \"Your Name\"")

    if out.json_mode:
        out.set_result(res)
        out.success(f"account {args.name} ready")
        return 0

    out.success(f"Account {args.name} ready" + (" (dry-run)" if args.dry_run else ""))
    if res["pubkey"] and not res.get("created_key"):
        out.plain(f"  Reused an existing key. If it isn't on {args.host} yet, add it (Settings → SSH keys):")
        out.plain(f"  {res['pubkey']}")
        out.plain(f"  Verify:  gwt ssh check {args.name} --live")
    elif res["pubkey"]:
        out.plain(f"  Upload this public key to {args.host} (Settings → SSH keys):")
        out.plain(f"  {res['pubkey']}")
        out.plain(f"  Then verify:  gwt ssh check {args.name} --live")
    elif not args.dry_run:
        out.plain(f"  Public key: {res['key']}.pub")
    return 0


def cmd_ssh_accounts(args, out: Output) -> int:
    from ...core import sshprov

    inv = sshprov.read_inventory()

    rows = []
    for a in inv.accounts:
        st = sshprov.key_status(a, out.git_echo)
        z = inv.zone_of(a)
        rows.append((a, st, z, inv.routing_state(a)))

    if out.json_mode:
        out.set_result({
            "accounts": [
                {
                    "name": a.name, "host": a.host, "key": a.key,
                    "key_exists": st.exists, "in_agent": st.in_agent,
                    "zone": (z.scope_dir if z else None),
                    "email": (z.email if z else None),
                    "routing": routing,
                }
                for (a, st, z, routing) in rows
            ],
            "zones": [
                {"scope_dir": z.scope_dir, "email": z.email,
                 "identity_path": z.identity_path, "rewrites": z.rewrites}
                for z in inv.zones
            ],
        })
        out.success(f"{len(inv.accounts)} account(s)")
        return 0

    if not rows:
        out.plain("No grove-managed SSH accounts. Add one with: gwt ssh add <name> --host <host> --email <email> --scope-dir <dir>")
        return 0

    _ROUTING = {"ok": ("✓", "green"), "partial": ("!", "yellow"), "none": ("—", "dim")}
    table = []
    for (a, st, z, routing) in rows:
        key = Path(a.key).name + (" ✓" if st.exists else " ✗") + (" agent" if st.in_agent is True else "")
        zone = f"{z.scope_dir}  {z.email}" if z else "—"
        table.append((a.name, a.host, key, zone, routing, st.exists))
    # Column widths from the content (plain text; colour is added afterwards).
    w = [max(len(h), *(len(r[i]) for r in table)) + 2
         for i, h in enumerate(("ACCOUNT", "HOST", "KEY", "ZONE"))]
    out.plain(f"{'ACCOUNT':<{w[0]}}{'HOST':<{w[1]}}{'KEY':<{w[2]}}{'ZONE':<{w[3]}}ROUTING")
    for name, host, key, zone, routing, exists in table:
        cell = f"{key:<{w[2]}}"
        if not exists:
            cell = cell.replace(" ✗", out._c(" ✗", "yellow"), 1)
        sym, color = _ROUTING[routing]
        out.plain(f"{name:<{w[0]}}{host:<{w[1]}}{cell}{zone:<{w[3]}}{out._c(sym, color)}")
    return 0


def cmd_ssh_remove(args, out: Output) -> int:
    from ...core import sshprov

    res = sshprov.remove_account(
        args.name,
        delete_key=args.delete_key,
        keep_routing=args.keep_routing,
        dry_run=args.dry_run,
    )
    for s in res["steps"]:
        out.step(s)
    if out.json_mode:
        out.set_result(res)
    out.success(f"Account {args.name} removed" + (" (dry-run)" if args.dry_run else ""))
    if not args.delete_key and not args.dry_run:
        out.plain("  (key files kept; pass --delete-key to remove them)")
    return 0


def cmd_ssh_doctor(args, out: Output) -> int:
    from ...core import sshdoctor

    git = GitRunner(on_command=out.git_echo)
    findings = sshdoctor.diagnose(git=git, echo=out.git_echo)
    auto = [f for f in findings if f.severity == "fix"]
    review = [f for f in findings if f.severity == "review"]

    _MARK = {"fix": ("✗", "red"), "review": ("!", "yellow")}

    if out.json_mode:
        applied = sshdoctor.apply_fixes(findings) if args.fix and auto else 0
        out.set_result({
            "findings": [
                {"check": f.check, "severity": f.severity, "target": f.target,
                 "message": f.message, "fixable": f.fixer is not None}
                for f in findings
            ],
            "auto_fixable": len(auto), "review": len(review), "applied": applied,
        })
        out.success(f"{len(findings)} finding(s); {len(auto)} auto-fixable, {len(review)} manual")
        return 1 if (len(review) or (auto and not args.fix)) else 0

    if not findings:
        out.success("No problems: the SSH/git multi-account setup is healthy.")
        return 0

    out.plain("Findings:")
    for f in findings:
        sym, color = _MARK[f.severity]
        out.plain(f"  {out._c(sym, color)} {f.check:<14} {f.target}")
        out.plain(f"      {f.message}")
    out.plain(f"{len(auto)} auto-fixable · {len(review)} require manual review.")

    if args.dry_run or not auto:
        return 1 if (review or auto) else 0

    do_fix = args.fix
    if not do_fix:
        try:
            ans = input(f"Apply the {len(auto)} automatic fixes? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        do_fix = ans in ("y", "yes")

    if do_fix:
        n = sshdoctor.apply_fixes(findings)
        out.success(f"{n} fix(es) applied.")
        return 1 if review else 0
    out.plain("No changes were applied.")
    return 1


def cmd_ssh_help(args, out: Output) -> int:
    out.plain("Usage: gwt ssh <check|accounts|add|doctor|remove> ...")
    out.plain("  gwt ssh check [<url-or-host>] [--all] [--live]")
    out.plain("  gwt ssh accounts            list grove-managed SSH accounts")
    out.plain("  gwt ssh add <name> --host <host> [--email <e> --scope-dir <dir>]")
    out.plain("  gwt ssh doctor [--fix] [--dry-run]   diagnose & repair the setup")
    out.plain("  gwt ssh remove <name> [--delete-key] [--keep-routing]")
    return 0


def register_ssh(sub) -> None:
    ssp = sub.add_parser("ssh", help="SSH configuration diagnostics")
    ssp.set_defaults(func=cmd_ssh_help)
    ssh_sub = ssp.add_subparsers(dest="ssh_command")
    chk = ssh_sub.add_parser("check", help="diagnose SSH for a remote")
    _common(chk)
    chk.add_argument("target", nargs="?", help="URL or host (default: repo origin)")
    chk.add_argument("--all", action="store_true", help="all Hosts in ~/.ssh/config")
    chk.add_argument("--live", action="store_true", help="authentication test (ssh -T)")
    chk.set_defaults(func=cmd_ssh_check)

    alp = ssh_sub.add_parser("aliases", help="show SSH aliases that match a repo/host (repo↔alias map)")
    _common(alp)
    alp.add_argument("target", nargs="?", help="URL or host (default: repo origin)")
    alp.set_defaults(func=cmd_ssh_aliases)

    acc = ssh_sub.add_parser("accounts", help="list grove-managed SSH accounts")
    _common(acc)
    acc.set_defaults(func=cmd_ssh_accounts)

    addp = ssh_sub.add_parser("add", help="provision an SSH account (key + config + git routing)")
    _common(addp)
    addp.add_argument("name", help="account name = SSH Host alias (e.g. dropi-gh)")
    addp.add_argument("--host", required=True, help="real host (github.com, bitbucket.org, …)")
    addp.add_argument("--email", help="git author email for this account's zone")
    addp.add_argument("--scope-dir", dest="scope_dir",
                      help="folder that routes this account (defines/joins a zone)")
    addp.add_argument("--key", help="private key path (default ~/.ssh/id_ed25519_<name>)")
    addp.add_argument("--no-identity", action="store_true",
                      help="configure SSH only; do not touch ~/.gitconfig")
    addp.add_argument("--no-agent", action="store_true", help="do not load the key into the agent")
    addp.add_argument("--no-passphrase", action="store_true",
                      help="generate the key without passphrase (headless/CI)")
    addp.add_argument("--print-pubkey", action="store_true", help="print only the public key")
    addp.add_argument("--dry-run", action="store_true", help="show planned edits without writing")
    addp.set_defaults(func=cmd_ssh_add)

    doc = ssh_sub.add_parser("doctor", help="diagnose & repair the SSH/git multi-account setup")
    _common(doc)
    doc.add_argument("--fix", action="store_true", help="apply automatic fixes without asking")
    doc.add_argument("--dry-run", action="store_true", help="only report, never modify")
    doc.set_defaults(func=cmd_ssh_doctor)

    rmp = ssh_sub.add_parser("remove", help="remove a grove-managed SSH account")
    _common(rmp)
    rmp.add_argument("name", help="account name to remove")
    rmp.add_argument("--delete-key", action="store_true", help="also delete the key files")
    rmp.add_argument("--keep-routing", action="store_true",
                     help="keep the git identity routing (only remove the SSH block)")
    rmp.add_argument("--dry-run", action="store_true", help="show planned edits without writing")
    rmp.set_defaults(func=cmd_ssh_remove)
