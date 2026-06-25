"""Marker-scoped, idempotent, atomic edits of user dotfiles.

Used for ``~/.ssh/config`` and ``~/.gitconfig`` (both use ``#`` comments). grove
only ever rewrites text **inside its sentinel markers**; any hand-written content
outside the markers is preserved byte-for-byte.

Marker format (``kind`` ∈ {``account``, ``zone``})::

    # >>> grove:account=dropi-gh >>>
    <body>
    # <<< grove:account=dropi-gh <<<
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .errors import ValidationError

_OPEN = "# >>> grove:{kind}={id} >>>"
_CLOSE = "# <<< grove:{kind}={id} <<<"

_MARKER_RE = re.compile(
    r"^#\s*(?P<dir>>>>|<<<)\s*grove:(?P<kind>\w+)=(?P<id>[\w.\-]+)\s*(?:>>>|<<<)\s*$"
)


# --------------------------------------------------------------------------- #
# Pure string operations
# --------------------------------------------------------------------------- #

def _find_region(lines: List[str], kind: str, id: str) -> Tuple[Optional[int], Optional[int]]:
    """(start, end) line indices of a marked region, or (None, None). Validates balance."""
    start: Optional[int] = None
    end: Optional[int] = None
    for i, line in enumerate(lines):
        m = _MARKER_RE.match(line.strip())
        if not m or m.group("kind") != kind or m.group("id") != id:
            continue
        if m.group("dir") == ">>>":
            if start is not None:
                raise ValidationError(f"Duplicate open marker grove:{kind}={id}")
            start = i
        else:
            if start is None:
                raise ValidationError(f"Close marker before open for grove:{kind}={id}")
            end = i
            break
    if start is not None and end is None:
        raise ValidationError(f"Unbalanced marker grove:{kind}={id} (missing close)")
    return start, end


def _join(lines: List[str], trailing: bool) -> str:
    s = "\n".join(lines)
    return s + "\n" if trailing else s


def upsert_block(text: str, kind: str, id: str, body: str) -> str:
    """Replace the existing marked region in place, or append a new one. Idempotent."""
    open_m = _OPEN.format(kind=kind, id=id)
    close_m = _CLOSE.format(kind=kind, id=id)
    region_lines = [open_m, *body.strip("\n").split("\n"), close_m]

    lines = text.split("\n")
    # text.split("\n") on a trailing newline yields a final "" element; track it.
    had_trailing = text.endswith("\n")
    if had_trailing and lines and lines[-1] == "":
        lines = lines[:-1]

    start, end = _find_region(lines, kind, id)
    if start is not None:
        new_lines = lines[:start] + region_lines + lines[end + 1:]
        return _join(new_lines, trailing=had_trailing or text == "")

    # Append a new region.
    if not text:
        return "\n".join(region_lines) + "\n"
    body_lines = list(lines)
    if body_lines and body_lines[-1].strip():
        body_lines.append("")  # blank-line separator before our region
    body_lines += region_lines
    return _join(body_lines, trailing=True)


def remove_block(text: str, kind: str, id: str) -> Tuple[str, bool]:
    """Drop a marked region (and the single separator blank line we may have added).
    Returns (new_text, removed?)."""
    lines = text.split("\n")
    had_trailing = text.endswith("\n")
    if had_trailing and lines and lines[-1] == "":
        lines = lines[:-1]

    start, end = _find_region(lines, kind, id)
    if start is None:
        return text, False

    drop_from = start
    # Consume one immediately-preceding blank line (our separator) to avoid pile-up.
    if start > 0 and lines[start - 1] == "":
        drop_from = start - 1

    new_lines = lines[:drop_from] + lines[end + 1:]
    if not new_lines or new_lines == [""]:
        return "", True
    return _join(new_lines, trailing=had_trailing), True


def find_blocks(text: str, kind: Optional[str] = None) -> Dict[str, str]:
    """{id: body} for every grove-managed region (optionally filtered by ``kind``)."""
    out: Dict[str, str] = {}
    cur_kind: Optional[str] = None
    cur_id: Optional[str] = None
    buf: List[str] = []
    for line in text.split("\n"):
        m = _MARKER_RE.match(line.strip())
        if m:
            if m.group("dir") == ">>>":
                cur_kind, cur_id, buf = m.group("kind"), m.group("id"), []
            elif cur_id and m.group("kind") == cur_kind and m.group("id") == cur_id:
                if kind is None or cur_kind == kind:
                    out[cur_id] = "\n".join(buf)
                cur_kind = cur_id = None
                buf = []
            continue
        if cur_id is not None:
            buf.append(line)
    return out


# --------------------------------------------------------------------------- #
# File helpers
# --------------------------------------------------------------------------- #

def read_text(path: Path) -> str:
    p = Path(path)
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def write_atomic(path: Path, text: str) -> None:
    """Write via tmp + os.replace (no half-written config); mkdir parents; chmod 600 (POSIX)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".grove-tmp")
    tmp.write_text(text, encoding="utf-8")
    if os.name != "nt":
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, p)


_BACKED_UP: set = set()


def reset_backup_cache() -> None:
    """Clear the per-run backup cache (used by tests)."""
    _BACKED_UP.clear()


def backup_once(path: Path, backups_dir: Path) -> Optional[Path]:
    """Snapshot the original file into ``backups_dir`` before the first edit of a run."""
    p = Path(path)
    key = str(p)
    if key in _BACKED_UP:
        return None
    _BACKED_UP.add(key)
    if not p.is_file():
        return None
    Path(backups_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = Path(backups_dir) / f"{p.name}.{ts}.bak"
    dest.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return dest
