"""Patch operation: generates a patch of a worktree (diff vs base, or format-patch)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from .gitrunner import GitRunner
from .model import Worktree
from .repo import RepoContext

Step = lambda m: None  # noqa: E731

PATCHES_SUBDIR = "patches"


def _slug(wt: Worktree) -> str:
    return wt.rel_path.replace("\\", "/").replace("/", "-")


def generate(
    git: GitRunner,
    repo: RepoContext,
    wt: Worktree,
    *,
    base: str,
    wip: bool = False,
    fmt_patch: bool = False,
    patches_dir: Optional[Path] = None,
    out_path: Optional[Path] = None,
    to_stdout: bool = False,
    step: Step = lambda m: None,
) -> dict:
    """Generates the patch. Returns a dict with mode/path/stdout/empty/files."""
    slug = _slug(wt)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # --- format-patch (per commit), only for committed range ---
    if fmt_patch and not wip:
        if to_stdout:
            text = git.out(["format-patch", f"{base}..HEAD", "--stdout"], cwd=wt.path)
            return {"mode": "format-patch", "stdout": text, "path": None,
                    "empty": not text.strip()}
        dest = out_path or ((patches_dir or Path.cwd()) / f"{slug}__{ts}")
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        step(f"git format-patch {base}..HEAD -> {dest}")
        git.run(["format-patch", f"{base}..HEAD", "-o", str(dest)], cwd=wt.path)
        files = sorted(p.name for p in dest.glob("*.patch"))
        return {"mode": "format-patch", "path": str(dest), "files": files,
                "empty": not files}

    # --- combined diff (committed range) or WIP (uncommitted) ---
    if wip:
        text = git.out(["diff", "HEAD"], cwd=wt.path)
        ext = "wip.diff"
        mode = "wip"
    else:
        text = git.out(["diff", f"{base}...HEAD"], cwd=wt.path)
        ext = "diff"
        mode = "diff"

    if to_stdout:
        return {"mode": mode, "stdout": text, "path": None, "empty": not text.strip()}

    if out_path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        base_dir = patches_dir or Path.cwd()
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / f"{slug}__{ts}.{ext}"

    path.write_text(text, encoding="utf-8")
    step(f"Patch written to {path}")
    return {"mode": mode, "path": str(path), "empty": not text.strip()}
