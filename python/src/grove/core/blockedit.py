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
import hashlib
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
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
    find_blocks("\n".join(lines))  # validate all regions, including duplicates elsewhere
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
    seen = set()
    cur_kind: Optional[str] = None
    cur_id: Optional[str] = None
    buf: List[str] = []
    for line in text.split("\n"):
        m = _MARKER_RE.match(line.strip())
        if m:
            if m.group("dir") == ">>>":
                if cur_id is not None:
                    raise ValidationError("Nested Grove markers; repair the file before editing.")
                marker = (m.group("kind"), m.group("id"))
                if marker in seen:
                    raise ValidationError(f"Duplicate Grove marker {marker[0]}={marker[1]}")
                seen.add(marker)
                cur_kind, cur_id, buf = m.group("kind"), m.group("id"), []
            elif cur_id and m.group("kind") == cur_kind and m.group("id") == cur_id:
                if kind is None or cur_kind == kind:
                    out[cur_id] = "\n".join(buf)
                cur_kind = cur_id = None
                buf = []
            else:
                raise ValidationError("Unmatched closing Grove marker; repair the file before editing.")
            continue
        if cur_id is not None:
            buf.append(line)
    if cur_id is not None:
        raise ValidationError(f"Unbalanced Grove marker {cur_kind}={cur_id} (missing close)")
    return out


# --------------------------------------------------------------------------- #
# File helpers
# --------------------------------------------------------------------------- #

def read_text(path: Path) -> str:
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    except UnicodeError as exc:
        raise ValidationError(f"Invalid UTF-8 in {p}; no configuration edit performed.") from exc


_UNCHECKED = object()


@contextmanager
def _file_lock(path: Path):
    """Cooperating writers lock a stable file while comparing and replacing.

    Keep the lock file: unlinking it allows two processes to lock different
    inodes. These are only created for real mutations, never for previews.
    """
    lock = path.with_name(f".{path.name}.grove-lock")
    with lock.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_atomic(path: Path, text: str, *, expected=_UNCHECKED) -> None:
    """Write via tmp + os.replace (no half-written config); mkdir parents; chmod 600 (POSIX)."""
    p = Path(path)
    if p.is_symlink():
        p = p.resolve(strict=True)  # preserve the user's config symlink
    find_blocks(text)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _EDIT_LOCK, _file_lock(p):
        if expected is not _UNCHECKED and read_text(p) != expected:
            raise ValidationError(f"Concurrent edit of {p}; no overwrite performed. Retry after review.")
        if p.is_file() and read_text(p) == text:
            return
        fd, name = tempfile.mkstemp(prefix=f".{p.name}.grove-", dir=p.parent)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)


_BACKED_UP: set = set()
_BACKUP_SCOPE = ContextVar("grove_backup_scope", default=None)
_EDIT_LOCK = RLock()


@contextmanager
def edit_scope():
    """One backup per file per operation, with reentrant in-process edits."""
    with _EDIT_LOCK:
        token = _BACKUP_SCOPE.set(set()) if _BACKUP_SCOPE.get() is None else None
        try:
            yield
        finally:
            if token is not None:
                _BACKUP_SCOPE.reset(token)


def reset_backup_cache() -> None:
    """Clear the per-run backup cache (used by tests)."""
    _BACKED_UP.clear()
    current = _BACKUP_SCOPE.get()
    if current is not None:
        current.clear()


def backup_once(path: Path, backups_dir: Path) -> Optional[Path]:
    """Snapshot the original file into ``backups_dir`` before the first edit of a run."""
    p = Path(path)
    key = str(p)
    cache = _BACKUP_SCOPE.get()
    cache = _BACKED_UP if cache is None else cache
    if key in cache:
        return None
    if not p.is_file():
        return None
    Path(backups_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    digest = hashlib.sha256(str(p.absolute()).encode()).hexdigest()[:12]
    fd, name = tempfile.mkstemp(prefix=f"{p.name}.{digest}.{ts}.", suffix=".bak", dir=backups_dir)
    dest = Path(name)
    with os.fdopen(fd, "wb") as stream:
        stream.write(p.read_bytes())
    cache.add(key)
    return dest
