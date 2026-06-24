"""Worktree convention policy.

The values in this module are the **defaults**. They are overridden at runtime
by loading the repo config (`.bare/grove.toml`) with `load()`, or by applying a
profile with `apply_profile()`. The core reads `config.X` on each call, so
mutating these globals once at the start of the command is enough.

Precedence (lowest to highest):
  internal defaults < profile/global config < repo config < environment < flags.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

try:                       # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover  (only interpreters < 3.11)
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None

# --------------------------------------------------------------------------- #
# Truly global constants (do not depend on context)
# --------------------------------------------------------------------------- #

RELEASE_TYPE = "release"
ORIGIN_REFSPEC = "+refs/heads/*:refs/remotes/origin/*"

# --------------------------------------------------------------------------- #
# Configurable policy (defaults)
# --------------------------------------------------------------------------- #

PARKING_BRANCH = "worktree-config-root"
DEFAULT_BASE = "production"
TICKET_TYPES = ("feature", "hotfix", "bugfix")
SPECIAL_WORKTREES = ("production", "temporary-unified-test")
TEMP_DIR = "temp"
RELEASE_FORMAT = "release/{version}"
RELEASE_DEFAULT_BASE = "production"

# Local artifacts/documentation folder (NOT a worktree; outside the tree of
# any branch, so it is never versioned or pushed). "" = disabled.
ARTIFACTS_DIR = "artifacts"

# Shared integration branch (destination of `publish`). "" = none.
INTEGRATION_BRANCH = "temporary-unified-test"

# ~/.ssh/config alias associated with this repo's remote. "" = none (canonical URL).
SSH_ALIAS = ""

# Git hosts for the `ssh check --all` fallback when there is no ~/.ssh/config.
KNOWN_GIT_HOSTS = ("github.com", "bitbucket.org", "gitlab.com")

# Tickets mode: "required" | "optional" | "off"
TICKETS = "required"

# Accepted project keys (list). None = generic pattern or explicit regex.
TICKET_PREFIXES = None  # type: ignore[assignment]

# Ticket pattern (recomputed in _compute_ticket_re).
TICKET_PATTERN = r"[A-Z][A-Z0-9]+-\d+"
TICKET_RE = re.compile(TICKET_PATTERN, re.IGNORECASE)

# Derived.
TYPE_FOLDERS = TICKET_TYPES + (RELEASE_TYPE,)


# --------------------------------------------------------------------------- #
# Built-in profiles (the global config can add/override)
# --------------------------------------------------------------------------- #

BUILTIN_PROFILES = {
    # Generic, neutral: base main, optional tickets, no own special branches.
    "default": {
        "default_base": "main",
        "allowed_types": ["feature", "fix", "hotfix"],
        "special_worktrees": [],
        "tickets": "optional",
        "integration_branch": "",
        "release": {"format": "release/{version}", "default_base": "main"},
    },
    # For personal projects: just as simple, base main.
    "personal": {
        "default_base": "main",
        "allowed_types": ["feature", "fix"],
        "special_worktrees": [],
        "tickets": "optional",
        "integration_branch": "",
        "release": {"format": "release/{version}", "default_base": "main"},
    },
    # Gitflow style: integration branch 'develop', tickets required.
    "gitflow": {
        "default_base": "main",
        "allowed_types": ["feature", "hotfix", "bugfix", "release"],
        "special_worktrees": ["develop"],
        "tickets": "required",
        "integration_branch": "develop",
        "release": {"format": "release/{version}", "default_base": "main"},
    },
}

DEFAULT_PROFILE = "default"

CONFIG_FILENAME = "grove.toml"
GLOBAL_CONFIG = Path.home() / ".config" / "grove" / "config.toml"


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _pattern_from_prefixes(prefixes) -> str:
    """Builds the regex `(?:A|B)-\\d+` from a list of keys."""
    keys = [re.escape(p.strip().upper()) for p in prefixes if str(p).strip()]
    if not keys:
        return r"[A-Z][A-Z0-9]+-\d+"
    return rf"(?:{'|'.join(keys)})-\d+"


def _compute_ticket_re(pattern: str) -> None:
    """Sets TICKET_RE from 'pattern'. GROVE_TICKET_PREFIX (one or more keys
    separated by comma/space) takes priority."""
    global TICKET_PATTERN, TICKET_RE
    env = os.environ.get("GROVE_TICKET_PREFIX", "").strip()
    if env:
        pattern = _pattern_from_prefixes(re.split(r"[,\s]+", env))
    TICKET_PATTERN = pattern
    TICKET_RE = re.compile(pattern, re.IGNORECASE)


def _read_toml(path: Path) -> dict:
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("Python 3.11+ (tomllib) is required to read the configuration.")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def apply_policy(policy: dict) -> None:
    """Overrides the module globals with a normalized policy dict."""
    global PARKING_BRANCH, DEFAULT_BASE, TICKET_TYPES, SPECIAL_WORKTREES
    global TEMP_DIR, RELEASE_FORMAT, RELEASE_DEFAULT_BASE, TICKETS, TYPE_FOLDERS
    global INTEGRATION_BRANCH, KNOWN_GIT_HOSTS, TICKET_PREFIXES, SSH_ALIAS, ARTIFACTS_DIR

    PARKING_BRANCH = policy.get("parking_branch", PARKING_BRANCH)
    DEFAULT_BASE = policy.get("default_base", DEFAULT_BASE)
    INTEGRATION_BRANCH = policy.get("integration_branch", INTEGRATION_BRANCH)
    SSH_ALIAS = policy.get("ssh_alias", SSH_ALIAS)
    ARTIFACTS_DIR = policy.get("artifacts_dir", ARTIFACTS_DIR)
    khosts = policy.get("known_git_hosts")
    if khosts is not None:
        KNOWN_GIT_HOSTS = tuple(khosts)

    types = policy.get("allowed_types")
    if types:
        # 'release' is always an available type; it does not count as a ticket type.
        TICKET_TYPES = tuple(t for t in types if t != RELEASE_TYPE)

    specials = policy.get("special_worktrees")
    if specials is not None:
        SPECIAL_WORKTREES = tuple(specials)

    TEMP_DIR = policy.get("temp_dir", TEMP_DIR)
    TICKETS = policy.get("tickets", TICKETS)

    release = policy.get("release", {}) or {}
    RELEASE_FORMAT = release.get("format", RELEASE_FORMAT)
    RELEASE_DEFAULT_BASE = release.get("default_base", DEFAULT_BASE)

    # Ticket pattern: explicit regex > list of keys > current pattern.
    if policy.get("ticket_pattern"):
        TICKET_PREFIXES = None
        _compute_ticket_re(policy["ticket_pattern"])
    elif policy.get("ticket_prefixes"):
        TICKET_PREFIXES = list(policy["ticket_prefixes"])
        _compute_ticket_re(_pattern_from_prefixes(TICKET_PREFIXES))
    else:
        _compute_ticket_re(TICKET_PATTERN)

    TYPE_FOLDERS = TICKET_TYPES + (RELEASE_TYPE,)


def resolve_profile(name: str) -> dict:
    """Returns the policy dict of a profile (global config takes priority over builtin)."""
    policy = dict(BUILTIN_PROFILES.get(name, {}))
    if GLOBAL_CONFIG.is_file():
        data = _read_toml(GLOBAL_CONFIG)
        profiles = data.get("profiles", {})
        if name in profiles:
            policy.update(profiles[name])
        elif name not in BUILTIN_PROFILES:
            raise KeyError(name)
    elif name not in BUILTIN_PROFILES:
        raise KeyError(name)
    return policy


def load(bare: Path) -> None:
    """Loads the repo config (`<bare>/grove.toml`) over the defaults, if it exists."""
    cfg = Path(bare) / CONFIG_FILENAME
    if cfg.is_file():
        apply_policy(_read_toml(cfg))
    else:
        # No file: still respects the prefix env.
        _compute_ticket_re(TICKET_PATTERN)


# --------------------------------------------------------------------------- #
# Serialization (there is no tomllib.dump in stdlib; we generate the subset we use)
# --------------------------------------------------------------------------- #

def _toml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(_toml_scalar(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def render_repo_config(policy: dict) -> str:
    """Generates the TOML text of `grove.toml` from a resolved policy dict."""
    lines = ["# grove configuration for this repo (generated by 'gwt setup').", ""]
    for key in ("parking_branch", "default_base", "allowed_types",
                "special_worktrees", "temp_dir", "artifacts_dir", "tickets",
                "ticket_prefixes", "ticket_pattern",
                "integration_branch", "ssh_alias", "known_git_hosts"):
        if key in policy and policy[key] is not None:
            lines.append(f"{key} = {_toml_scalar(policy[key])}")
    release = policy.get("release") or {}
    if release:
        lines += ["", "[release]"]
        for key in ("format", "default_base"):
            if key in release and release[key] is not None:
                lines.append(f"{key} = {_toml_scalar(release[key])}")
    return "\n".join(lines) + "\n"


def write_repo_config(bare: Path, policy: dict) -> Path:
    cfg = Path(bare) / CONFIG_FILENAME
    cfg.write_text(render_repo_config(policy), encoding="utf-8")
    return cfg


def effective_policy() -> dict:
    """Snapshot of the active policy (to write grove.toml after setup)."""
    pol = {
        "parking_branch": PARKING_BRANCH,
        "default_base": DEFAULT_BASE,
        "allowed_types": list(TICKET_TYPES),
        "special_worktrees": list(SPECIAL_WORKTREES),
        "temp_dir": TEMP_DIR,
        "artifacts_dir": ARTIFACTS_DIR,
        "tickets": TICKETS,
        "integration_branch": INTEGRATION_BRANCH,
        "ssh_alias": SSH_ALIAS,
        "known_git_hosts": list(KNOWN_GIT_HOSTS),
        "release": {"format": RELEASE_FORMAT, "default_base": RELEASE_DEFAULT_BASE},
    }
    # Emits the friendly form (list of keys) if configured that way; otherwise the regex.
    if TICKET_PREFIXES:
        pol["ticket_prefixes"] = list(TICKET_PREFIXES)
    else:
        pol["ticket_pattern"] = TICKET_PATTERN
    return pol
