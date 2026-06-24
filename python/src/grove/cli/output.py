"""Presentation: symbols, colors, verbose and interactive confirmation."""

from __future__ import annotations

import os
import sys
from typing import Sequence

_COLORS = {
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def _supports_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform == "win32":
        # Win10+ / Windows Terminal support VT; we try to enable it.
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            return False
    return True


class Output:
    def __init__(self, *, quiet: bool = False, no_color: bool = False,
                 verbose: bool = False, json_mode: bool = False):
        self.quiet = quiet
        self.verbose = verbose
        self.json_mode = json_mode
        self.color = (not no_color) and (not json_mode) and _supports_color(sys.stdout)
        # In JSON mode nothing loose is printed: it accumulates and main() emits the envelope.
        self.log = []          # type: list[str]
        self.result = None     # optional structured payload set by each command
        self.message = None    # last success / summary message

    def _c(self, text: str, color: str) -> str:
        if not self.color:
            return text
        return f"{_COLORS[color]}{text}{_COLORS['reset']}"

    def step(self, msg: str) -> None:
        if self.json_mode:
            self.log.append(msg)
            return
        if not self.quiet:
            print(f"{self._c('→', 'dim')} {msg}")

    def success(self, msg: str) -> None:
        self.message = msg
        if self.json_mode:
            self.log.append(msg)
            return
        if not self.quiet:
            print(f"{self._c('✓', 'green')} {msg}")

    def warn(self, msg: str) -> None:
        if self.json_mode:
            self.log.append(msg)
            return
        print(f"{self._c('!', 'yellow')} {msg}")

    def error(self, msg: str) -> None:
        # In JSON mode main() emits the error inside the envelope.
        if self.json_mode:
            self.log.append(msg)
            return
        print(f"{self._c('✗', 'red')} {msg}", file=sys.stderr)

    def plain(self, msg: str = "") -> None:
        if self.json_mode:
            if msg:
                self.log.append(msg)
            return
        print(msg)

    def set_result(self, payload) -> None:
        self.result = payload

    # ---- callbacks for GitRunner ----

    def git_echo(self, cmd: Sequence[str]) -> None:
        if self.verbose:
            print(f"  {self._c('$ ' + ' '.join(cmd), 'dim')}")

    def confirm_git(self, cmd: Sequence[str]) -> bool:
        try:
            ans = input(f"  run «{' '.join(cmd)}» ? [y/N] ").strip().lower()
        except EOFError:
            return False
        return ans in ("y", "yes")
