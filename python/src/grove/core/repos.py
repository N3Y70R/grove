"""Discover grove-managed repos on this machine (`gwt repos`).

An agent often knows a repo by name ("the grove repo", "dropi-business-rules")
but every grove operation needs its absolute path. grove keeps no registry of
repos, so this looks for folders containing `.bare/` under a few roots: the
directories given, else the identity zones configured with `gwt ssh add`
(`includeIf gitdir:` scopes). The walk is shallow and skips hidden folders and
the inside of repos already found.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from . import platform as plat

DEFAULT_DEPTH = 3
_SKIP = {"node_modules", "__pycache__", "venv", "Library", "Applications"}


def is_managed(path: Path) -> bool:
    bare = Path(path) / ".bare"
    return bare.is_dir() and (bare / "HEAD").is_file()


def zone_roots(paths: Optional[plat.Paths] = None) -> List[Path]:
    """Existing directories of the configured identity zones."""
    from . import sshprov
    try:
        inv = sshprov.read_inventory(paths or plat.paths())
    except Exception:           # unreadable ssh/git config: no zones
        return []
    roots: List[Path] = []
    for z in inv.zones:
        raw = z.scope_dir
        for suffix in ("/**", "**"):
            if raw.endswith(suffix):
                raw = raw[: -len(suffix)]
        p = Path(os.path.expanduser(raw.rstrip("/") or "/"))
        if p.is_dir() and p not in roots:
            roots.append(p)
    return roots


def _read_toml(path: Path) -> dict:
    try:
        import tomllib                                  # Python 3.11+
    except ImportError:                                 # pragma: no cover
        import tomli as tomllib                         # type: ignore
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _describe(repo: Path) -> dict:
    bare = repo / ".bare"

    # The URL git really uses: `remote get-url` applies url.insteadOf rewrites
    # (e.g. a zone's https://github.com/ → git@work-gh:), like grove_config.
    r = subprocess.run(["git", "--git-dir", str(bare), "remote", "get-url", "origin"],
                       capture_output=True, text=True)
    origin = (r.stdout.strip() or None) if r.returncode == 0 else None

    policy = _read_toml(bare / "grove.toml")
    base = policy.get("default_base") or None
    if not base:                   # no grove.toml: the bare HEAD is the base (since 0.10.0)
        head = subprocess.run(["git", "--git-dir", str(bare), "symbolic-ref", "-q", "--short", "HEAD"],
                              capture_output=True, text=True)
        base = head.stdout.strip() or None
        if base == policy.get("parking_branch", "worktree-config-root"):
            base = None
    # Effective profile, as grove loads it: a grove.toml without `profile` (or
    # no grove.toml) layers on the default profile.
    profile = policy.get("profile") or "default"
    return {"path": str(repo), "name": repo.name, "origin": origin,
            "base": base, "profile": profile}


def find(roots: Sequence[Path], depth: int = DEFAULT_DEPTH) -> List[dict]:
    found: List[dict] = []
    seen = set()
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        base_depth = len(root.resolve().parts)
        for dirpath, dirnames, _files in os.walk(root):
            d = Path(dirpath)
            if is_managed(d):
                key = d.resolve()
                if key not in seen:
                    seen.add(key)
                    found.append(_describe(d))
                dirnames[:] = []          # never descend into a managed repo
                continue
            if len(d.resolve().parts) - base_depth >= depth:
                dirnames[:] = []
                continue
            dirnames[:] = sorted(n for n in dirnames if not n.startswith(".") and n not in _SKIP)
    return sorted(found, key=lambda r: r["path"])


def discover(paths: Optional[Sequence[str]] = None, depth: int = DEFAULT_DEPTH) -> dict:
    """Managed repos under `paths`, else under the identity zones."""
    if paths:
        roots = [Path(p).expanduser() for p in paths]
        source = "paths"
    else:
        roots = zone_roots()
        source = "zones"
    repos = find(roots, depth)
    hint = None
    if not roots:
        hint = ("no identity zones configured: pass the folders to search, "
                "e.g. `gwt repos ~/code`, or ask the user for the repo's path")
    elif not repos:
        hint = "no grove-managed repo found; try a larger depth or other folders"
    return {"roots": [str(r) for r in roots], "source": source, "depth": depth,
            "repos": repos, "count": len(repos), "hint": hint}
