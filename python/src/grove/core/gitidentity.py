"""Git identity layer: global hardening + per-folder zones (includeIf + insteadOf).

Two mechanisms by design:

* **Plain global scalars** (``user.name``, ``user.useConfigOnly``) are written with
  ``git config --global`` — git owns its own scalars.
* **Structured regions** (the ``includeIf`` block in ``~/.gitconfig`` and the
  grove-owned zone identity file) are written with marker-scoped ``blockedit``,
  because ``includeIf`` is conditional and we need idempotent upsert + removal.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import blockedit
from . import platform as plat

_URL_KEY_RE = re.compile(r'^\[url\s+"git@(?P<alias>[\w.\-]+):"\]')
_HOST_FROM_INSTEADOF = re.compile(r'(?:git@|https://)(?P<host>[\w.\-]+)[:/]')


# --------------------------------------------------------------------------- #
# Global scalars (via git config)
# --------------------------------------------------------------------------- #

def _get_global(git, key: str) -> str:
    return git.run(["config", "--global", "--get", key],
                   check=False, mutating=False).stdout.strip()


def harden_global(git, name: Optional[str] = None) -> dict:
    """Ensure `user.useConfigOnly=true` (so git can never auto-invent an identity)
    and, if missing and `name` is given, `user.name`. Returns {changes, name}."""
    changes: List[str] = []
    if _get_global(git, "user.useConfigOnly").lower() != "true":
        git.run(["config", "--global", "user.useConfigOnly", "true"])
        changes.append("user.useConfigOnly = true")
    cur_name = _get_global(git, "user.name")
    if not cur_name and name:
        git.run(["config", "--global", "user.name", name])
        cur_name = name
        changes.append(f"user.name = {name}")
    return {"changes": changes, "name": cur_name}


def conflicting_url_rewrites(git) -> List[Tuple[str, str]]:
    """Global `url.*` rewrites (for doctor to review; e.g. token-bearing ones)."""
    proc = git.run(["config", "--global", "--get-regexp", r"^url\."],
                   check=False, mutating=False)
    out: List[Tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if " " in line:
            k, v = line.split(" ", 1)
            out.append((k.strip(), v.strip()))
    return out


# --------------------------------------------------------------------------- #
# Identity file (grove-owned: safe to rewrite wholesale)
# --------------------------------------------------------------------------- #

def zone_id_for(scope_dir) -> str:
    """Stable id/filename from a folder (e.g. '~/dropi/' -> 'dropi')."""
    name = Path(os.path.expanduser(str(scope_dir))).name
    slug = re.sub(r"[^\w.\-]+", "-", name).strip("-").lower()
    return slug or "zone"


def render_identity(email: str, rewrites: Dict[str, str]) -> str:
    """Text of a zone identity file: [user] email + url.insteadOf per account."""
    lines = ["# grove-owned identity file — managed by `gwt ssh`. Do not edit by hand.",
             "", "[user]", f"    email = {email}"]
    for host, alias in sorted(rewrites.items()):
        lines += ["", f'[url "git@{alias}:"]',
                  f"    insteadOf = git@{host}:",
                  f"    insteadOf = https://{host}/"]
    return "\n".join(lines) + "\n"


def read_identity(path: Path) -> Tuple[str, Dict[str, str]]:
    """(email, {host: alias}) parsed from a zone identity file ('' / {} if absent)."""
    text = blockedit.read_text(path)
    email = ""
    rewrites: Dict[str, str] = {}
    cur_alias: Optional[str] = None
    in_user = False
    for raw in text.splitlines():
        s = raw.strip()
        mk = _URL_KEY_RE.match(s)
        if mk:
            cur_alias, in_user = mk.group("alias"), False
            continue
        if s.lower().startswith("[user]"):
            in_user, cur_alias = True, None
            continue
        if s.startswith("["):
            in_user, cur_alias = False, None
            continue
        if in_user and s.lower().startswith("email"):
            email = _value(s) or email
        elif cur_alias and s.lower().startswith("insteadof"):
            mh = _HOST_FROM_INSTEADOF.search(_value(s) or "")
            if mh:
                rewrites[mh.group("host")] = cur_alias
    return email, rewrites


def _value(line: str) -> Optional[str]:
    return line.split("=", 1)[1].strip() if "=" in line else None


# --------------------------------------------------------------------------- #
# Zone upsert / removal (includeIf + identity file)
# --------------------------------------------------------------------------- #

def upsert_zone(scope_dir, email: str, rewrites: Dict[str, str],
                paths: plat.Paths, *, dry_run: bool = False) -> Path:
    """Create/update the includeIf in ~/.gitconfig + the zone identity file.
    `rewrites` = {host: alias}; merged into the existing zone (adds an account)."""
    gitdir = plat.normalize_gitdir(scope_dir)
    zid = zone_id_for(scope_dir)
    identity_path = paths.identities_dir / f"{zid}.gitconfig"

    existing_email, existing_rewrites = read_identity(identity_path)
    merged = dict(existing_rewrites)
    merged.update(rewrites)
    final_email = email or existing_email

    if dry_run:
        return identity_path

    blockedit.backup_once(identity_path, paths.backups_dir)
    blockedit.write_atomic(identity_path, render_identity(final_email, merged))

    include_body = f'[includeIf "gitdir:{gitdir}"]\n    path = {identity_path}'
    git_text = blockedit.read_text(paths.gitconfig)
    blockedit.backup_once(paths.gitconfig, paths.backups_dir)
    blockedit.write_atomic(
        paths.gitconfig,
        blockedit.upsert_block(git_text, "zone", zid, include_body),
    )
    return identity_path


def remove_account_from_zone(scope_dir, alias: str, paths: plat.Paths,
                             *, dry_run: bool = False) -> bool:
    """Drop one account's rewrites; if the zone becomes empty, remove the
    includeIf block and the identity file."""
    zid = zone_id_for(scope_dir)
    identity_path = paths.identities_dir / f"{zid}.gitconfig"
    email, rewrites = read_identity(identity_path)
    remaining = {h: a for h, a in rewrites.items() if a != alias}
    if dry_run:
        return True
    if remaining:
        blockedit.backup_once(identity_path, paths.backups_dir)
        blockedit.write_atomic(identity_path, render_identity(email, remaining))
    else:
        git_text = blockedit.read_text(paths.gitconfig)
        new_git, _ = blockedit.remove_block(git_text, "zone", zid)
        blockedit.backup_once(paths.gitconfig, paths.backups_dir)
        blockedit.write_atomic(paths.gitconfig, new_git)
        try:
            Path(identity_path).unlink()
        except OSError:
            pass
    return True
