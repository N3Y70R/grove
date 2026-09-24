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
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from . import platform as plat
from .errors import ValidationError

SKILL_NAME = "grove"


def bundled_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "_skill" / SKILL_NAME


def _files() -> List[str]:
    base = bundled_dir()
    return sorted(str(p.relative_to(base)).replace("\\", "/")
                  for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


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
    """Copy the bundled skill to <dest_root>/grove. Never overwrites a file that
    differs (edited, or another version) unless force=True."""
    src, dest = bundled_dir(), Path(dest_root) / SKILL_NAME
    files = _files()
    differ = [f for f in files if (dest / f).exists() and not filecmp.cmp(src / f, dest / f, shallow=False)]
    missing = [f for f in files if not (dest / f).exists()]
    if not dest.exists():
        mode = "created"
    elif not differ and not missing:
        mode = "unchanged"
    else:
        if differ and not force:
            raise ValidationError(
                f"{dest} differs from grove's skill ({', '.join(differ)}): it was edited or is "
                f"another version. Re-run with force to overwrite.")
        mode = "updated"
    if not dry_run and mode != "unchanged":
        for f in files:
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / f, dest / f)
    return {"skill": SKILL_NAME, "path": str(dest), "mode": mode, "files": files,
            "dry_run": dry_run}
