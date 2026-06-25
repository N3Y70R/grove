"""SSH account/zone model and read-only inventory (phase 2).

The source of truth is the canonical files (``~/.ssh/config`` and ``~/.gitconfig``
plus the grove-owned identity files they include). grove does not keep a parallel
registry: ``read_inventory`` *derives* the inventory from the marker-scoped blocks
(``blockedit``). Provisioning (``add``/``remove``) lands in phase 3.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import blockedit
from . import gitidentity
from . import platform as plat
from .errors import GitError, ValidationError
from .gitrunner import GitRunner

# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #


@dataclass
class Account:
    name: str          # == SSH Host alias (also the marker id)
    host: str          # HostName (real host)
    key: str           # IdentityFile (expanded)
    managed: bool = True
    zone_dir: Optional[str] = None   # intended zone (from a `# grove-zone:` annotation)


@dataclass
class Zone:
    scope_dir: str               # gitdir pattern (expanded)
    email: str
    identity_path: str
    rewrites: Dict[str, str] = field(default_factory=dict)   # host -> alias


@dataclass
class Inventory:
    accounts: List[Account] = field(default_factory=list)
    zones: List[Zone] = field(default_factory=list)

    def zone_by_dir(self, scope_dir: str) -> Optional[Zone]:
        for z in self.zones:
            if z.scope_dir == scope_dir:
                return z
        return None

    def zone_of(self, account: Account) -> Optional[Zone]:
        """The zone for this account: by its `zone_dir` annotation, else by rewrite membership."""
        if account.zone_dir:
            z = self.zone_by_dir(account.zone_dir)
            if z is not None:
                return z
        for z in self.zones:
            if account.name in z.rewrites.values():
                return z
        return None

    def routing_state(self, account: Account) -> str:
        """'ok' | 'partial' | 'none' — coherence of the git identity routing."""
        z = self.zone_of(account)
        if z is None:
            return "none"
        return "ok" if z.rewrites.get(account.host) == account.name else "partial"


@dataclass
class AddSpec:
    name: str
    host: str
    email: Optional[str] = None
    scope_dir: Optional[Path] = None
    key: Optional[Path] = None
    no_identity: bool = False
    no_agent: bool = False
    no_passphrase: bool = False
    dry_run: bool = False


# --------------------------------------------------------------------------- #
# Parsing helpers (grove-owned formats; tolerant)
# --------------------------------------------------------------------------- #

_GITDIR_RE = re.compile(r'gitdir:\s*(?P<dir>[^"\]]+)')
_NAME_RE = re.compile(r"^[A-Za-z0-9][\w.\-]*$")


def _kv(line: str) -> Optional[str]:
    """Value of an `ssh_config`-style `Key value` line (after the first whitespace)."""
    parts = line.strip().split(None, 1)
    return parts[1].strip() if len(parts) > 1 else None


def _parse_account_body(name: str, body: str) -> Account:
    host = ""
    key = ""
    zone_dir: Optional[str] = None
    for line in body.splitlines():
        s = line.strip()
        low = s.lower()
        if low.startswith("# grove-zone:"):
            zone_dir = s.split(":", 1)[1].strip()
        elif low.startswith("hostname"):
            host = _kv(line) or ""
        elif low.startswith("identityfile"):
            key = _kv(line) or ""
    return Account(name=name, host=host, key=os.path.expanduser(key),
                   managed=True, zone_dir=zone_dir)


def _parse_zone(body: str) -> Optional[Zone]:
    scope_dir = ""
    identity_path = ""
    for line in body.splitlines():
        m = _GITDIR_RE.search(line)
        if m:
            scope_dir = m.group("dir").strip()
        elif line.strip().lower().startswith("path"):
            identity_path = os.path.expanduser(line.split("=", 1)[1].strip()) if "=" in line else ""
    if not identity_path:
        return None
    email, rewrites = gitidentity.read_identity(Path(identity_path))
    return Zone(scope_dir=scope_dir, email=email,
                identity_path=identity_path, rewrites=rewrites)


# --------------------------------------------------------------------------- #
# Public read API
# --------------------------------------------------------------------------- #

def read_inventory(paths: Optional[plat.Paths] = None) -> Inventory:
    """Derive accounts (from ~/.ssh/config) and zones (from ~/.gitconfig + identity files)."""
    p = paths or plat.paths()

    inv = Inventory()
    ssh_text = blockedit.read_text(p.ssh_config)
    for name, body in blockedit.find_blocks(ssh_text, "account").items():
        inv.accounts.append(_parse_account_body(name, body))

    git_text = blockedit.read_text(p.gitconfig)
    for _id, body in blockedit.find_blocks(git_text, "zone").items():
        z = _parse_zone(body)
        if z is not None:
            inv.zones.append(z)

    inv.accounts.sort(key=lambda a: a.name)
    inv.zones.sort(key=lambda z: z.scope_dir)
    return inv


# --------------------------------------------------------------------------- #
# Per-account key status (for `accounts` rendering)
# --------------------------------------------------------------------------- #

@dataclass
class KeyStatus:
    exists: bool
    in_agent: Optional[bool]   # None = could not determine (no agent)


def key_status(account: Account, echo=None) -> KeyStatus:
    from .sshcheck import _agent_fingerprints, _fingerprint_of

    key = Path(account.key)
    exists = key.is_file()
    in_agent: Optional[bool] = None
    if exists:
        running, fps = _agent_fingerprints(echo)
        if running and fps:
            fp = _fingerprint_of(key, echo)
            in_agent = (fp in fps) if fp else None
    return KeyStatus(exists=exists, in_agent=in_agent)


# --------------------------------------------------------------------------- #
# Write path (phase 3): add / remove
# --------------------------------------------------------------------------- #

def _slug(name: str) -> str:
    return re.sub(r"[^\w]+", "_", name)


def _tilde(path: Path, paths: plat.Paths) -> str:
    """Render a path with `~` if under home (portable in ssh_config)."""
    home = str(paths.home)
    s = str(path)
    if s == home:
        return "~"
    if s.startswith(home + os.sep):
        return "~" + s[len(home):]
    return s


def _render_host_block(name: str, host: str, key_display: str,
                       zone_dir: Optional[str] = None) -> str:
    lines = [
        f"Host {name}",
        f"    HostName {host}",
        "    User git",
        f"    IdentityFile {key_display}",
        "    IdentitiesOnly yes",
    ]
    if zone_dir:
        lines.append(f"    # grove-zone: {zone_dir}")
    return "\n".join(lines)


def _keygen_if_missing(key: Path, comment: str, no_passphrase: bool,
                       dry_run: bool, echo=None) -> bool:
    """Generate the ed25519 key if absent. Returns True if it (would be) created.

    Passphrase: interactive by default (inherit stdio so the user can type); with
    `no_passphrase` an empty passphrase (`-N ""`) is used for headless/JSON/CI."""
    if key.is_file():
        return False
    if dry_run:
        return True
    key.parent.mkdir(parents=True, exist_ok=True)
    args = ["ssh-keygen", "-t", "ed25519", "-C", comment, "-f", str(key)]
    if echo:
        echo(args)
    if no_passphrase:
        proc = subprocess.run(args + ["-N", ""], text=True, capture_output=True)
        if proc.returncode != 0:
            raise GitError(f"ssh-keygen failed: {(proc.stderr or '').strip()}")
    else:
        if subprocess.run(args).returncode != 0:   # inherit stdio for the prompt
            raise GitError("ssh-keygen failed")
    plat.enforce_key_perms(key)
    return True


def add_account(spec: AddSpec, git: Optional[GitRunner] = None,
                paths: Optional[plat.Paths] = None, echo=None) -> dict:
    """Provision an account: key + ~/.ssh/config block + (optional) git identity routing."""
    p = paths or plat.paths()
    git = git or GitRunner(dry_run=spec.dry_run, on_command=echo)

    if not _NAME_RE.match(spec.name):
        raise ValidationError(f"Invalid account name '{spec.name}' (use letters, digits, -, _).")
    if not spec.host:
        raise ValidationError("A --host is required.")
    wants_identity = not spec.no_identity and spec.scope_dir is not None
    if wants_identity and not spec.email:
        raise ValidationError("--email is required for identity routing (or pass --no-identity).")

    key = Path(spec.key) if spec.key else p.ssh_dir / f"id_ed25519_{_slug(spec.name)}"
    steps: List[str] = []

    created = _keygen_if_missing(key, spec.name, spec.no_passphrase, spec.dry_run, echo)
    steps.append(f"{'generate' if created else 'reuse'} key {_tilde(key, p)}")

    zone_dir = plat.normalize_gitdir(spec.scope_dir) if wants_identity else None

    # SSH config: ensure defaults block, then upsert the account block.
    text = blockedit.read_text(p.ssh_config)
    if "defaults" not in blockedit.find_blocks(text, "defaults"):
        text = blockedit.upsert_block(text, "defaults", "defaults", plat.ssh_defaults_block())
        steps.append("write ~/.ssh/config defaults (Host *)")
    body = _render_host_block(spec.name, spec.host, _tilde(key, p), zone_dir)
    text = blockedit.upsert_block(text, "account", spec.name, body)
    steps.append(f"write ~/.ssh/config block [grove:account={spec.name}]")
    if not spec.dry_run:
        blockedit.backup_once(p.ssh_config, p.backups_dir)
        blockedit.write_atomic(p.ssh_config, text)

    name_missing = False
    if wants_identity:
        h = gitidentity.harden_global(git, name=None)
        steps += [f"harden ~/.gitconfig: {c}" for c in h["changes"]]
        name_missing = not h["name"]
        gitidentity.upsert_zone(spec.scope_dir, spec.email, {spec.host: spec.name},
                                p, dry_run=spec.dry_run)
        steps.append(f"route git@{spec.host}: -> git@{spec.name}: "
                     f"(zone {gitidentity.zone_id_for(spec.scope_dir)}, email {spec.email})")

    if not spec.no_agent and not spec.dry_run and key.is_file():
        if plat.agent_add(key, echo):
            steps.append("load key into agent")

    pubkey = ""
    pub = Path(str(key) + ".pub")
    if not spec.dry_run and pub.is_file():
        pubkey = blockedit.read_text(pub).strip()

    return {
        "name": spec.name, "host": spec.host, "key": str(key),
        "created_key": created, "pubkey": pubkey,
        "zone": zone_dir, "email": (spec.email if wants_identity else None),
        "name_missing": name_missing, "dry_run": spec.dry_run, "steps": steps,
    }


def remove_account(name: str, *, delete_key: bool = False, keep_routing: bool = False,
                   dry_run: bool = False, paths: Optional[plat.Paths] = None,
                   echo=None) -> dict:
    """Remove a grove-managed account: ssh block + (optional) its zone routing."""
    p = paths or plat.paths()
    inv = read_inventory(p)
    account = next((a for a in inv.accounts if a.name == name), None)
    if account is None:
        raise ValidationError(f"No grove-managed account '{name}'.")
    zone = inv.zone_of(account)
    steps: List[str] = []

    text = blockedit.read_text(p.ssh_config)
    new_text, removed = blockedit.remove_block(text, "account", name)
    if removed:
        steps.append(f"remove ~/.ssh/config block [grove:account={name}]")
        if not dry_run:
            blockedit.backup_once(p.ssh_config, p.backups_dir)
            blockedit.write_atomic(p.ssh_config, new_text)

    if zone and not keep_routing:
        gitidentity.remove_account_from_zone(zone.scope_dir, name, p, dry_run=dry_run)
        steps.append(f"remove routing for {name} from zone {gitidentity.zone_id_for(zone.scope_dir)}")

    if delete_key and not dry_run:
        for f in (Path(account.key), Path(account.key + ".pub")):
            try:
                f.unlink()
            except OSError:
                pass
        steps.append(f"delete key {account.key}")

    return {"name": name, "deleted_key": delete_key, "dry_run": dry_run, "steps": steps}
