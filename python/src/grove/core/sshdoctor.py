"""Diagnose & repair the SSH + git multi-account setup (phase 4).

Encodes the failure modes documented in the SSH guide. Mirrors the worktree
``doctor`` (spec §6.7): auto-fixable items carry a ``fixer``; report-only items
require human judgment and are never touched automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from . import blockedit
from . import gitidentity
from . import platform as plat
from . import sshprov
from .gitrunner import GitRunner

_CREDS_IN_URL = re.compile(r"://[^/@\s]+:[^/@\s]+@")   # https://user:token@host


@dataclass
class Finding:
    check: str
    severity: str                 # 'fix' (auto) | 'review' (manual)
    target: str
    message: str
    fixer: Optional[Callable[[], None]] = None


# --------------------------------------------------------------------------- #
# Diagnosis
# --------------------------------------------------------------------------- #

def diagnose(paths: Optional[plat.Paths] = None, git: Optional[GitRunner] = None,
             echo=None, interactive: bool = False) -> List[Finding]:
    p = paths or plat.paths()
    git = git or GitRunner(on_command=echo)
    inv = sshprov.read_inventory(p)
    findings: List[Finding] = []

    findings += _check_accounts(inv, p, echo, interactive)
    findings += _check_zones(inv, p)
    findings += _check_global(git)
    findings += _check_trap(inv, p)
    findings += _check_effective(inv, p, echo)
    return findings


def _check_accounts(inv, p, echo, interactive=False) -> List[Finding]:
    out: List[Finding] = []
    ssh_text = blockedit.read_text(p.ssh_config)
    blocks = blockedit.find_blocks(ssh_text, "account")

    for a in inv.accounts:
        key = Path(a.key)
        if not key.is_file():
            out.append(Finding("orphan", "review", a.name,
                               f"key {a.key} is missing (block kept)"))
            continue

        if plat.check_key_perms(key) is False:
            out.append(Finding("perms", "fix", a.name,
                               f"key {Path(a.key).name} has open permissions",
                               fixer=(lambda k=key: plat.enforce_key_perms(k))))

        body = blocks.get(a.name, "")
        if not re.search(r"(?im)^\s*IdentitiesOnly\s+yes\s*(?:#.*)?$", body):
            out.append(Finding("identitiesonly", "fix", a.name,
                               "Host block lacks 'IdentitiesOnly yes'",
                               fixer=_fix_identitiesonly(p, a.name)))

        st = sshprov.key_status(a, echo)
        if st.in_agent is False:
            out.append(Finding("agent", "fix", a.name,
                               "key not loaded in ssh-agent",
                               fixer=(lambda k=key: plat.agent_add(k, echo, interactive=interactive))))
    return out


def _check_zones(inv, p) -> List[Finding]:
    out: List[Finding] = []
    seen_dirs = set()
    ambiguous = set()
    for z in inv.zones:
        related = [other for other in inv.zones if other.scope_dir == z.scope_dir or Path(other.identity_path).resolve() == Path(z.identity_path).resolve()]
        if len(related) > 1:
            ambiguous.add(z.scope_dir)
            out.append(Finding("ambiguous-zone", "review", z.scope_dir,
                               "multiple zones share a scope or identity file; review includes and backups before repair"))
    for z in inv.zones:
        if not Path(z.identity_path).is_file():
            out.append(Finding("missing-identity", "review", z.identity_path,
                               "zone include points to a missing identity file; restore it before repair"))
    for a in inv.accounts:
        z = inv.zone_of(a)
        if z is None:
            if a.zone_dir:   # block declares a zone that no longer exists
                out.append(Finding("orphan", "review", a.name,
                                   f"declares zone {a.zone_dir} but no includeIf/identity file"))
            continue
        if z.scope_dir in ambiguous or not Path(z.identity_path).is_file():
            continue
        if z.scope_dir not in seen_dirs and not Path(z.scope_dir).exists():
            seen_dirs.add(z.scope_dir)
            out.append(Finding("orphan", "review", z.scope_dir,
                               "zone scope_dir does not exist on disk"))
        # account routed by a zone but its host rewrite is missing/incorrect
        if z.rewrites.get(a.host) != a.name:
            out.append(Finding("insteadof", "fix", a.name,
                               f"missing insteadOf git@{a.host}: -> git@{a.name}:",
                               fixer=_fix_insteadof(p, z.scope_dir, z.email, a.host, a.name)))
    return out


def _check_global(git) -> List[Finding]:
    out: List[Finding] = []
    if gitidentity._get_global(git, "user.useConfigOnly").lower() != "true":
        out.append(Finding("useconfigonly", "fix", "~/.gitconfig",
                           "user.useConfigOnly unset → git may auto-invent an identity",
                           fixer=lambda: gitidentity.run_global(
                               git, ["config", "--global", "user.useConfigOnly", "true"])))
    if not gitidentity._get_global(git, "user.name"):
        out.append(Finding("username", "review", "~/.gitconfig",
                           "global user.name is not set "
                           "(set with: git config --global user.name \"Your Name\")"))
    for key, val in gitidentity.conflicting_url_rewrites(git):
        if _CREDS_IN_URL.search(key) or _CREDS_IN_URL.search(val):
            out.append(Finding("secret", "review", "url.insteadOf",
                               "embedded credential in a global url rewrite — rotate & remove manually"))
    return out


def _config_host_names(p: plat.Paths) -> set:
    """All `Host` tokens declared in ~/.ssh/config (excluding wildcards)."""
    names = set()
    for line in blockedit.read_text(p.ssh_config).splitlines():
        s = line.strip()
        if s.lower().startswith("host "):
            for tok in s.split()[1:]:
                if "*" not in tok and "?" not in tok:
                    names.add(tok)
    return names


def _check_trap(inv, p) -> List[Finding]:
    """Host-vs-alias trap: a real host with neither a dedicated `Host` block nor a
    working insteadOf rewrite. Then a canonical `git@<host>:` remote falls through to
    `Host *` (IdentitiesOnly, no key) and fails — the exact bug from the guide.

    Not flagged when an account on that host has a working rewrite (canonical URLs are
    rewritten to the alias, so the real host is never contacted)."""
    host_names = _config_host_names(p)
    out: List[Finding] = []
    for host in sorted({a.host for a in inv.accounts}):
        if host in host_names:
            continue  # a dedicated Host block covers the real host
        accts = [a for a in inv.accounts if a.host == host]
        if any(inv.routing_state(a) == "ok" for a in accts):
            continue  # insteadOf rewrites canonical → alias; real host not used
        out.append(Finding("trap", "review", host,
                           f"git@{host}: has no Host block and no insteadOf rewrite → "
                           f"falls through to 'Host *' (IdentitiesOnly, no key) and would fail; "
                           f"add a Host {host} block, or route it with a zone, or use the alias"))
    return out


def _check_effective(inv, p, echo=None) -> List[Finding]:
    """OpenSSH resolves ordering, wildcards, includes and Match; never edit manual blocks."""
    from .sshcheck import _run
    out = []
    if not inv.accounts or not p.ssh_config.is_file():
        return out
    for account in inv.accounts:
        proc = _run(["ssh", "-F", str(p.ssh_config), "-G", account.name], echo=echo)
        if proc.returncode != 0:
            out.append(Finding("effective-config", "review", account.name,
                               "Unable to resolve SSH configuration; review it with ssh -G."))
            continue
        values = {}
        for line in proc.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                values.setdefault(parts[0].lower(), []).append(parts[1])
        keys = {str(Path(value.replace("~", str(p.home), 1)).absolute())
                for value in values.get("identityfile", [])}
        if (values.get("hostname", [""])[0] != account.host or
                values.get("user", [""])[0] != "git" or
                values.get("identitiesonly", [""])[0] != "yes" or
                str(Path(account.key).absolute()) not in keys):
            out.append(Finding("effective-config", "review", account.name,
                               "Effective SSH settings differ from the managed account; review preceding manual blocks, Include and Match rules."))
    return out


# --------------------------------------------------------------------------- #
# Fixers
# --------------------------------------------------------------------------- #

def _fix_identitiesonly(p: plat.Paths, name: str) -> Callable[[], None]:
    def _do() -> None:
        text = blockedit.read_text(p.ssh_config)
        body = blockedit.find_blocks(text, "account").get(name, "")
        if not re.search(r"(?im)^\s*IdentitiesOnly\s+yes\s*(?:#.*)?$", body):
            body = re.sub(r"(?im)^\s*IdentitiesOnly\s+[^\n]*\n?", "", body)
            body = body.rstrip("\n") + "\n    IdentitiesOnly yes"
        blockedit.backup_once(p.ssh_config, p.backups_dir)
        blockedit.write_atomic(p.ssh_config,
                               blockedit.upsert_block(text, "account", name, body), expected=text)
    return _do


def _fix_insteadof(p: plat.Paths, scope_dir: str, email: str,
                   host: str, alias: str) -> Callable[[], None]:
    def _do() -> None:
        gitidentity.upsert_zone(scope_dir, email, {host: alias}, p)
    return _do


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #

def apply_fixes(findings: List[Finding]) -> int:
    from .repairs import execute
    result = execute((f.check, f.target, f.fixer) for f in findings
                     if f.severity == "fix" and f.fixer is not None)
    return len(result["completed"])


def finding_dict(f: Finding) -> dict:
    return {"check": f.check, "severity": f.severity, "target": f.target,
            "message": f.message, "fixable": f.fixer is not None}


def report(*, fix=False, dry_run=False, findings=None, paths=None, git=None,
           echo=None, interactive=False) -> dict:
    """One CLI/MCP result, with post-repair diagnosis and explicit failures."""
    from .repairs import execute
    findings = diagnose(paths=paths, git=git, echo=echo, interactive=interactive) if findings is None else findings
    auto = [f for f in findings if f.severity == "fix" and f.fixer is not None]
    outcome = {"attempted": 0, "completed": [], "failures": []}
    remaining = findings
    dry_run = dry_run or bool(git and git.dry_run)
    if fix and not dry_run and auto:
        outcome = execute((f.check, f.target, f.fixer) for f in auto)
        remaining = diagnose(paths=paths, git=git, echo=echo, interactive=interactive)
    pending = {(f.check, f.target) for f in remaining}
    applied = sum(key not in pending for key in outcome["completed"])
    return {"findings": [finding_dict(f) for f in findings],
            "auto_fixable": len(auto), "review": sum(f.severity == "review" for f in findings),
            "applied": applied, "attempted": outcome["attempted"],
            "failures": outcome["failures"],
            "remaining_findings": [finding_dict(f) for f in remaining],
            "dry_run": dry_run}
