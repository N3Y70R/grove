"""Naming convention: slug, parsing and classification of worktrees."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from . import config


def slugify(text: str) -> str:
    """Normalizes a description to an ASCII-safe slug (valid on NTFS)."""
    # Strip accents.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    # Anything that is not alphanumeric -> hyphen.
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def extract_ticket(text: str) -> Optional[str]:
    """Returns the ticket key (e.g. ABC-123) in uppercase, or None."""
    m = config.TICKET_RE.search(text)
    return m.group(0).upper() if m else None


@dataclass
class Classification:
    """Classification of a worktree based on its relative path and its branch."""

    kind: str  # 'special' | 'temp' | 'ticket' | 'release' | 'unknown'
    type: Optional[str] = None  # feature/hotfix/bugfix/release
    ticket: Optional[str] = None
    version: Optional[str] = None


def classify(rel_path: str, branch: Optional[str]) -> Classification:
    """Classifies a worktree by its relative path within the repo.

    rel_path uses '/' as separator (POSIX), independent of the OS.
    """
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    head = parts[0] if parts else ""

    if head in config.SPECIAL_WORKTREES or rel_path in config.SPECIAL_WORKTREES:
        return Classification(kind="special")

    if head == config.TEMP_DIR:
        return Classification(kind="temp")

    if head == config.RELEASE_TYPE:
        version = "/".join(parts[1:]) if len(parts) > 1 else None
        return Classification(kind="release", type="release", version=version)

    if head in config.TICKET_TYPES:
        ticket = extract_ticket(rel_path) or (extract_ticket(branch) if branch else None)
        return Classification(kind="ticket", type=head, ticket=ticket)

    return Classification(kind="unknown")


def parse_origin_branch(branch: str) -> Classification:
    """Parses an origin branch name to place it in the structure.

    Reuses classify(): the branch name already has the form <type>/...
    """
    return classify(branch, branch)
