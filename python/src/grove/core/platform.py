"""OS layer for SSH account provisioning.

Isolates every platform-specific behavior (config paths, key permissions,
ssh-agent loading, keychain support, ``gitdir`` normalization) so the rest of the
provisioning logic stays shared across macOS, Linux and Windows.

Paths are resolved **per call** from ``$HOME`` / ``%USERPROFILE%`` (not bound at
import time) so tests can redirect the home directory and Windows is handled.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

Echo = Callable[[Sequence[str]], None]


@dataclass(frozen=True)
class Paths:
    home: Path
    ssh_dir: Path
    ssh_config: Path
    gitconfig: Path
    identities_dir: Path
    backups_dir: Path


def _home() -> Path:
    """Home directory. Honors HOME / USERPROFILE so tests and Windows both work."""
    env = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    return Path(env) if env else Path.home()


def paths() -> Paths:
    home = _home()
    return Paths(
        home=home,
        ssh_dir=home / ".ssh",
        ssh_config=home / ".ssh" / "config",
        gitconfig=home / ".gitconfig",
        identities_dir=home / ".config" / "grove" / "identities",
        backups_dir=home / ".config" / "grove" / "backups",
    )


# --------------------------------------------------------------------------- #
# Platform predicates
# --------------------------------------------------------------------------- #

def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def keychain_supported() -> bool:
    """The macOS Keychain integration (`UseKeychain`, `--apple-use-keychain`)."""
    return is_macos()


# --------------------------------------------------------------------------- #
# Key permissions
# --------------------------------------------------------------------------- #

def check_key_perms(path: Path) -> Optional[bool]:
    """True/False on POSIX (no group/other access). None (N/A) on Windows (NTFS ACLs)."""
    if is_windows():
        return None
    try:
        mode = Path(path).stat().st_mode & 0o777
    except OSError:
        return None
    return (mode & 0o077) == 0


def enforce_key_perms(path: Path) -> Optional[bool]:
    """`chmod 600` on POSIX; returns True/False. None (N/A) on Windows."""
    if is_windows():
        return None
    try:
        Path(path).chmod(0o600)
    except OSError:
        return False
    return True


# --------------------------------------------------------------------------- #
# ssh-agent
# --------------------------------------------------------------------------- #

def _run(args: Sequence[str], echo: Optional[Echo] = None):
    if echo:
        echo(list(args))
    try:
        return subprocess.run(args, text=True, capture_output=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]}: not found")


def agent_running() -> bool:
    """Whether an ssh-agent is reachable. `ssh-add -l` returns 2 when it is not."""
    proc = _run(["ssh-add", "-l"])
    return proc.returncode not in (2, 127)


def agent_add(key: Path, echo: Optional[Echo] = None) -> bool:
    """Load a key into the agent. Uses the macOS Keychain when available."""
    args = ["ssh-add"]
    if keychain_supported():
        args.append("--apple-use-keychain")
    args.append(str(key))
    return _run(args, echo=echo).returncode == 0


# --------------------------------------------------------------------------- #
# Config fragments
# --------------------------------------------------------------------------- #

def ssh_defaults_block() -> str:
    """The `Host *` defaults block; `UseKeychain yes` only on macOS."""
    lines = ["Host *", "    AddKeysToAgent yes"]
    if keychain_supported():
        lines.append("    UseKeychain yes")
    lines += ["    IdentitiesOnly yes", "    ServerAliveInterval 60"]
    return "\n".join(lines)


def normalize_gitdir(scope_dir: Path) -> str:
    """Absolute, forward-slashed, trailing-'/' path — the form git's `gitdir:` expects
    on every OS. Does not resolve symlinks or require the folder to exist."""
    p = Path(os.path.expanduser(str(scope_dir)))
    if not p.is_absolute():
        p = _home() / p
    text = p.as_posix()
    if not text.endswith("/"):
        text += "/"
    return text
