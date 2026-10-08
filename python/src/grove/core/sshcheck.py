"""SSH configuration diagnostics for git remotes (`ssh check` command).

Read-only. Uses `ssh -G` to resolve the effective config (includes Include/Match
/wildcards); manual parsing of ~/.ssh/config is used only to enumerate Hosts.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from .platform import paths as _paths

Echo = Callable[[Sequence[str]], None]

SSH_CONFIG = Path.home() / ".ssh" / "config"
_INITIAL_SSH_CONFIG = SSH_CONFIG


def ssh_config_path():
    return SSH_CONFIG if SSH_CONFIG != _INITIAL_SSH_CONFIG else _paths().ssh_config

# Patterns that indicate successful authentication in the live test.
_LIVE_OK_PATTERNS = (
    "successfully authenticated",
    "logged in as",
    "authenticated via",
)


@dataclass
class IdentityInfo:
    path: str
    exists: bool
    perms_ok: Optional[bool]   # None = N/A (e.g. Windows)
    loaded: Optional[bool]     # None = could not be determined


@dataclass
class LiveResult:
    ok: bool
    message: str


@dataclass
class HostReport:
    target: str
    hostname: Optional[str] = None
    user: Optional[str] = None
    identities_only: Optional[bool] = None
    identities: List[IdentityInfo] = field(default_factory=list)
    agent_running: bool = False
    agent_keys: List[str] = field(default_factory=list)
    live: Optional[LiveResult] = None
    error: Optional[str] = None
    config_present: bool = True   # does ~/.ssh/config exist?


SSH_DIR = Path.home() / ".ssh"
_INITIAL_SSH_DIR = SSH_DIR


def ssh_dir_path():
    return SSH_DIR if SSH_DIR != _INITIAL_SSH_DIR else _paths().ssh_dir
_NON_KEY_NAMES = {"config", "known_hosts", "known_hosts.old", "authorized_keys", "environment"}


# --------------------------------------------------------------------------- #
# Process helpers
# --------------------------------------------------------------------------- #

def _run(args: Sequence[str], echo: Optional[Echo] = None, timeout: Optional[int] = 10):
    if echo:
        echo(list(args))
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]}: not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")


# --------------------------------------------------------------------------- #
# URL / host parsing
# --------------------------------------------------------------------------- #

def host_from_url(url: str) -> Optional[str]:
    """Extracts the host (ssh alias) from a git URL. None if it is not SSH."""
    url = url.strip()
    # scp-like: [user@]host:path
    m = re.match(r"^(?:([^@]+)@)?([^:/]+):", url)
    if m and "://" not in url:
        return m.group(2)
    # ssh://[user@]host[:port]/path
    m = re.match(r"^ssh://(?:[^@]+@)?([^:/]+)", url)
    if m:
        return m.group(1)
    # https:// does not use SSH
    return None


# --------------------------------------------------------------------------- #
# Resolution with ssh -G
# --------------------------------------------------------------------------- #

def _ssh_g(host: str, echo: Optional[Echo] = None):
    """Returns (cfg, error). error is None if all is well, or the reason from ssh -G."""
    proc = _run(["ssh", "-F", str(ssh_config_path()) if ssh_config_path().is_file() else os.devnull, "-G", host], echo=echo)
    cfg: dict = {}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        return cfg, (err[0] if err else "ssh -G failed")
    for line in proc.stdout.splitlines():
        if " " in line:
            k, v = line.split(" ", 1)
            k = k.lower()
            if k == "identityfile":
                cfg.setdefault("identityfile", []).append(v)
            else:
                cfg.setdefault(k, v)
    return cfg, None


def _agent_fingerprints(echo: Optional[Echo] = None):
    """Returns (running, [fingerprints]) by querying ssh-add -l."""
    proc = _run(["ssh-add", "-l"], echo=echo)
    if proc.returncode == 2:        # could not contact the agent
        return False, []
    fps = []
    for line in proc.stdout.splitlines():
        m = re.search(r"(SHA256:[A-Za-z0-9+/=]+|MD5:[0-9a-f:]+)", line)
        if m:
            fps.append(m.group(1))
    return proc.returncode in (0, 1), fps


def _fingerprint_of(path: Path, echo: Optional[Echo] = None) -> Optional[str]:
    proc = _run(["ssh-keygen", "-lf", str(path)], echo=echo)
    if proc.returncode != 0:
        return None
    m = re.search(r"(SHA256:[A-Za-z0-9+/=]+)", proc.stdout)
    return m.group(1) if m else None


def _identity_info(raw_path: str, agent_fps: List[str], echo: Optional[Echo]) -> IdentityInfo:
    path = Path(os.path.expanduser(raw_path))
    exists = path.exists()

    perms_ok: Optional[bool] = None
    loaded: Optional[bool] = None

    if exists:
        if sys.platform != "win32":
            mode = path.stat().st_mode & 0o777
            perms_ok = (mode & 0o077) == 0      # neither group nor others
        fp = _fingerprint_of(path, echo)
        if fp is not None and agent_fps:
            loaded = fp in agent_fps
    return IdentityInfo(path=str(path), exists=exists, perms_ok=perms_ok, loaded=loaded)


def check_host(host: str, *, live: bool = False, echo: Optional[Echo] = None) -> HostReport:
    rep = HostReport(target=host, config_present=ssh_config_path().is_file())
    cfg, err = _ssh_g(host, echo)
    if err:
        rep.error = f"ssh -G failed: {err}"
        return rep

    rep.hostname = cfg.get("hostname")
    rep.user = cfg.get("user")
    rep.identities_only = (cfg.get("identitiesonly", "no").lower() == "yes")

    rep.agent_running, agent_fps = _agent_fingerprints(echo)
    rep.agent_keys = agent_fps

    for raw in cfg.get("identityfile", []):
        rep.identities.append(_identity_info(raw, agent_fps, echo))

    if live:
        rep.live = _live_test(host, cfg.get("user"), echo)
    return rep


def _live_test(host: str, user: Optional[str], echo: Optional[Echo]) -> LiveResult:
    target = f"{user}@{host}" if user else host
    proc = _run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
         "-o", "StrictHostKeyChecking=accept-new", target],
        echo=echo, timeout=15,
    )
    out = (proc.stdout + "\n" + proc.stderr).strip()
    low = out.lower()
    if any(p in low for p in _LIVE_OK_PATTERNS):
        return LiveResult(ok=True, message=out.splitlines()[0] if out else "authenticated")
    if proc.returncode == 124:
        return LiveResult(ok=False, message="timeout while connecting")
    if "permission denied" in low:
        return LiveResult(ok=False, message="permission denied (key not accepted)")
    return LiveResult(ok=False, message=out.splitlines()[0] if out else "no recognizable response")


# --------------------------------------------------------------------------- #
# Enumeration for --all
# --------------------------------------------------------------------------- #

def list_local_keys(echo: Optional[Echo] = None) -> List[IdentityInfo]:
    """Private keys present in ~/.ssh (heuristic), for users without config."""
    if not ssh_dir_path().is_dir():
        return []
    _, agent_fps = _agent_fingerprints(echo)
    keys: List[IdentityInfo] = []
    for f in sorted(ssh_dir_path().iterdir()):
        if not f.is_file():
            continue
        name = f.name
        if name.endswith(".pub") or name in _NON_KEY_NAMES or name.startswith("."):
            continue
        # It is a key if it has a .pub pair or follows the id_* pattern.
        if (f.parent / (name + ".pub")).exists() or name.startswith("id_"):
            keys.append(_identity_info(str(f), agent_fps, echo))
    return keys


def list_config_hosts() -> List[str]:
    """Hosts declared in ~/.ssh/config (skips wildcard patterns)."""
    if not ssh_config_path().is_file():
        return []
    hosts: List[str] = []
    for line in ssh_config_path().read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith("host "):
            for token in s.split()[1:]:
                if "*" not in token and "?" not in token and token not in hosts:
                    hosts.append(token)
    return hosts


def report_dict(rep) -> dict:
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
