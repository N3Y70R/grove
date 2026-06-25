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
             echo=None) -> List[Finding]:
    p = paths or plat.paths()
    git = git or GitRunner(on_command=echo)
    inv = sshprov.read_inventory(p)
    findings: List[Finding] = []

    findings += _check_accounts(inv, p, echo)
    findings += _check_zones(inv, p)
    findings += _check_global(git)
    findings += _check_trap(inv, p)
    return findings


def _check_accounts(inv, p, echo) -> List[Finding]:
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
        if "identitiesonly" not in body.lower():
            out.append(Finding("identitiesonly", "fix", a.name,
                               "Host block lacks 'IdentitiesOnly yes'",
                               fixer=_fix_identitiesonly(p, a.name)))

        st = sshprov.key_status(a, echo)
        if st.in_agent is False:
            out.append(Finding("agent", "fix", a.name,
                               "key not loaded in ssh-agent",
                               fixer=(lambda k=key: plat.agent_add(k, echo))))
    return out


def _check_zones(inv, p) -> List[Finding]:
    out: List[Finding] = []
    seen_dirs = set()
    for a in inv.accounts:
        z = inv.zone_of(a)
        if z is None:
            if a.zone_dir:   # block declares a zone that no longer exists
                out.append(Finding("orphan", "review", a.name,
                                   f"declares zone {a.zone_dir} but no includeIf/identity file"))
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
                           fixer=lambda: git.run(["config", "--global",
                                                  "user.useConfigOnly", "true"])))
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


# --------------------------------------------------------------------------- #
# Fixers
# --------------------------------------------------------------------------- #

def _fix_identitiesonly(p: plat.Paths, name: str) -> Callable[[], None]:
    def _do() -> None:
        text = blockedit.read_text(p.ssh_config)
        body = blockedit.find_blocks(text, "account").get(name, "")
        if "identitiesonly" not in body.lower():
            body = body.rstrip("\n") + "\n    IdentitiesOnly yes"
        blockedit.backup_once(p.ssh_config, p.backups_dir)
        blockedit.write_atomic(p.ssh_config,
                               blockedit.upsert_block(text, "account", name, body))
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
    n = 0
    for f in findings:
        if f.severity == "fix" and f.fixer is not None:
            f.fixer()
            n += 1
    return n
