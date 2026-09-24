"""grove's Agent Skill: install the bundled `grove` skill for AI agents.

The skill (https://agentskills.io) teaches an agent how to work with grove —
the recommended flow, which tool fits which request, and the gotchas. The
canonical copy lives in the repo at `skills/grove/`; the wheel ships an
identical copy (`grove/_skill/grove`, kept in sync by a test), so the installed
skill always matches the installed grove version.

Targets: `~/.agents/skills` (the cross-client convention, default),
`~/.claude/skills`, the current worktree's `.agents/skills` (project level),
or any directory.
"""

from __future__ import annotations

import filecmp
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import platform as plat
from .errors import ValidationError

SKILL_NAME = "grove"
# Written next to an installed copy: grove version + a hash per file, so
# `doctor` can tell an untouched copy (safe to refresh) from an edited one.
MANIFEST = ".grove-install.json"
_VERSION_RE = re.compile(r'^\s*grove-version:\s*["\']?([^"\'\s]+)', re.M)


def current_version() -> str:
    from .. import __version__
    return __version__


def bundled_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "_skill" / SKILL_NAME


def _files() -> List[str]:
    base = bundled_dir()
    return sorted(str(p.relative_to(base)).replace("\\", "/")
                  for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version_of(skill_dir: Path) -> Optional[str]:
    """The `metadata.grove-version` of a skill folder's SKILL.md (None if absent)."""
    try:
        text = (Path(skill_dir) / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    head = text.split("\n---", 1)[0] if text.startswith("---") else ""
    m = _VERSION_RE.search(head)
    return m.group(1) if m else None


def _read_manifest(skill_dir: Path) -> Optional[Dict]:
    try:
        data = json.loads((Path(skill_dir) / MANIFEST).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None
    except (OSError, ValueError):
        return None


def _write_manifest(skill_dir: Path, files: List[str]) -> None:
    data = {"grove_version": current_version(),
            "files": {f: _sha(Path(skill_dir) / f) for f in files}}
    (Path(skill_dir) / MANIFEST).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def status(skill_dir: Path) -> dict:
    """State of an installed copy against the running grove.

    `edited` is True/False when the copy has an install manifest (written since
    0.13.0), None when it doesn't (installed by 0.12.0 or copied by hand).
    """
    skill_dir = Path(skill_dir)
    installed = version_of(skill_dir)
    manifest = _read_manifest(skill_dir)
    edited: Optional[bool] = None
    if manifest is not None:
        edited = False
        for f, digest in manifest["files"].items():
            p = skill_dir / f
            if not p.is_file() or _sha(p) != digest:
                edited = True
                break
    current = current_version()
    return {"path": str(skill_dir), "installed_version": installed,
            "current_version": current, "outdated": installed != current, "edited": edited}


def default_roots() -> List[Path]:
    """User-level skills directories grove installs into (checked by doctor)."""
    return [target_root("agents"), target_root("claude")]


def target_root(target: str = "agents", *, cwd: Optional[Path] = None) -> Path:
    """Skills directory for a target: agents | claude | project."""
    home = plat.paths().home
    if target == "agents":
        return home / ".agents" / "skills"
    if target == "claude":
        return home / ".claude" / "skills"
    if target == "project":
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(cwd or Path.cwd()),
                           capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            raise ValidationError(
                "target 'project' needs a git worktree as the current directory "
                "(the skill goes into <worktree>/.agents/skills).")
        return Path(r.stdout.strip()) / ".agents" / "skills"
    raise ValidationError(f"Unknown target '{target}' (agents, claude or project).")


def install(*, dest_root: Path, force: bool = False, dry_run: bool = False) -> dict:
    """Copy the bundled skill to <dest_root>/grove.

    A copy that differs is refreshed when its install manifest shows it was not
    edited (typically: installed by an older grove). An edited copy, or one with
    no manifest, is only overwritten with force=True."""
    src, dest = bundled_dir(), Path(dest_root) / SKILL_NAME
    files = _files()
    differ = [f for f in files if (dest / f).exists() and not filecmp.cmp(src / f, dest / f, shallow=False)]
    missing = [f for f in files if not (dest / f).exists()]
    if not dest.exists():
        mode = "created"
    elif not differ and not missing:
        mode = "unchanged"
    else:
        st = status(dest) if differ else None
        if differ and not force and st["edited"] is not False:
            if st["installed_version"] != st["current_version"]:
                why = (f"the installed copy is for grove {st['installed_version'] or '(unknown)'}, "
                       f"this grove is {st['current_version']}")
                why += (", and it was edited" if st["edited"]
                        else ", and it has no install manifest to prove it wasn't edited")
            else:
                why = ("it was edited" if st["edited"]
                       else "it has no install manifest to prove it wasn't edited")
            raise ValidationError(
                f"{dest} differs from grove's skill ({', '.join(differ)}): {why}. "
                f"Re-run with force to overwrite.")
        mode = "updated"
    if not dry_run and mode != "unchanged":
        for f in files:
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / f, dest / f)
    if not dry_run and (mode != "unchanged" or _read_manifest(dest) is None):
        _write_manifest(dest, files)
    return {"skill": SKILL_NAME, "path": str(dest), "mode": mode, "files": files,
            "dry_run": dry_run}
