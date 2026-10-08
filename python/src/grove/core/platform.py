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
    override = os.environ.get("GIT_CONFIG_GLOBAL")
    if override is not None:
        gitconfig = Path(os.path.expanduser(override))
        if not gitconfig.is_absolute():
            gitconfig = home / gitconfig  # global Git operations run from home
    else:
        gitconfig = home / ".gitconfig"
        xdg = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "git" / "config"
        if not gitconfig.exists() and xdg.is_file():
            gitconfig = xdg
    return Paths(
        home=home,
        ssh_dir=home / ".ssh",
        ssh_config=home / ".ssh" / "config",
        gitconfig=gitconfig,
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

def _run(args: Sequence[str], echo: Optional[Echo] = None, *, interactive=False, timeout=10):
    if echo:
        echo(list(args))
    try:
        env = None if interactive else {**os.environ, "SSH_ASKPASS_REQUIRE": "never"}
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                              stdin=None if interactive else subprocess.DEVNULL,
                              start_new_session=not interactive, env=env)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]}: not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout; unlock the key in a terminal and retry")


def git_process_running() -> Optional[bool]:
    """Whether any git process is running on this machine.

    True/False when it could be determined; None when it couldn't (no `ps` /
    `tasklist`, or it failed). Used by doctor to decide whether a lock file is
    orphaned. Only this machine is visible: a git running in another
    environment that mounts the same repo is not detected.
    """
    try:
        if is_windows():
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq git.exe", "/NH"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                return None
            return "git.exe" in r.stdout.lower()
        r = subprocess.run(["ps", "-A", "-o", "comm="],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            name = os.path.basename(line.strip())
            if name == "git" or name.startswith("git-"):
                return True
        return False
    except (OSError, subprocess.SubprocessError):
        return None


def agent_running() -> bool:
    """Whether an ssh-agent is reachable. `ssh-add -l` returns 2 when it is not."""
    proc = _run(["ssh-add", "-l"])
    return proc.returncode in (0, 1)


def agent_add(key: Path, echo: Optional[Echo] = None, *, interactive=False) -> bool:
    """Load a key into the agent. Uses the macOS Keychain when available."""
    args = ["ssh-add"]
    if keychain_supported():
        args.append("--apple-use-keychain")
    args.append(str(key))
    return _run(args, echo=echo, interactive=interactive, timeout=60 if interactive else 10).returncode == 0


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
    text = Path(os.path.normpath(str(p))).as_posix()
    if not text.endswith("/"):
        text += "/"
    return text
