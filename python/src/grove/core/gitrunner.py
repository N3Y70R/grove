"""Subprocess wrapper for git.

Keeps the core decoupled from the CLI: presentation effects (verbose,
interactive confirmation) are injected via callbacks. dry_run is handled here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence

from .errors import GitError


class GitRunner:
    def __init__(
        self,
        cwd: Optional[Path] = None,
        *,
        dry_run: bool = False,
        on_command: Optional[Callable[[Sequence[str]], None]] = None,
        confirm: Optional[Callable[[Sequence[str]], bool]] = None,
    ) -> None:
        self.cwd = Path(cwd) if cwd else None
        self.dry_run = dry_run
        self._on_command = on_command
        self._confirm = confirm

    def _full_args(self, args: Sequence[str], cwd: Optional[Path]) -> list[str]:
        base = ["git"]
        target = cwd if cwd is not None else self.cwd
        if target is not None:
            base += ["-C", str(target)]
        return base + list(args)

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Optional[Path] = None,
        check: bool = True,
        capture: bool = True,
        mutating: bool = True,
    ) -> subprocess.CompletedProcess:
        """Runs `git <args>`.

        mutating=False marks reads (not skipped in dry_run nor confirmed).
        """
        full = self._full_args(args, cwd)

        if self._on_command is not None:
            self._on_command(full)

        if mutating and self._confirm is not None:
            if not self._confirm(full):
                raise GitError("Operation cancelled by the user.")

        if mutating and self.dry_run:
            # Not executed; returns a simulated empty result.
            return subprocess.CompletedProcess(full, 0, "", "")

        proc = subprocess.run(
            full,
            cwd=None,  # we use -C, not the process cwd
            text=True,
            capture_output=capture,
            encoding="utf-8",
        )
        if check and proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise GitError(f"git {' '.join(args)} failed: {msg}")
        return proc

    def out(self, args: Sequence[str], *, cwd: Optional[Path] = None) -> str:
        """Shortcut for reads: returns stripped stdout."""
        return self.run(args, cwd=cwd, mutating=False).stdout.strip()

    def ok(self, args: Sequence[str], *, cwd: Optional[Path] = None) -> bool:
        """True if the command exits with code 0 (read, without raising)."""
        return self.run(args, cwd=cwd, check=False, mutating=False).returncode == 0
