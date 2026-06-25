"""Shared fixtures for the grove test suite.

Two kinds of tests live here:

* Pure unit tests (naming, config, compare, sshalias) — no git, no I/O.
* Integration tests — exercise the real operations against a throwaway
  local git origin built in a temp directory.

Because ``grove.core.config`` keeps policy as module-level globals that the
operations read at call time, ``_reset_config`` snapshots and restores them
around every test so profiles applied in one test never leak into another.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from grove.core import config as cfg
from grove.core import setup as core_setup
from grove.core.gitrunner import GitRunner

# Globals mutated by config.apply_policy() / _compute_ticket_re().
_CFG_NAMES = (
    "PARKING_BRANCH", "DEFAULT_BASE", "TICKET_TYPES", "SPECIAL_WORKTREES",
    "TEMP_DIR", "RELEASE_FORMAT", "RELEASE_DEFAULT_BASE", "TICKETS",
    "TYPE_FOLDERS", "INTEGRATION_BRANCH", "KNOWN_GIT_HOSTS", "TICKET_PREFIXES",
    "SSH_ALIAS", "ARTIFACTS_DIR", "TICKET_PATTERN", "TICKET_RE",
)


@pytest.fixture(autouse=True)
def _reset_config():
    """Restore config module globals to their pre-test values."""
    snapshot = {name: getattr(cfg, name) for name in _CFG_NAMES}
    yield
    for name, value in snapshot.items():
        setattr(cfg, name, value)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Deterministic git identity and no ambient ticket-prefix override."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    monkeypatch.delenv("GROVE_TICKET_PREFIX", raising=False)


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd), check=True, capture_output=True, text=True,
    )


@pytest.fixture
def origin(tmp_path):
    """A bare origin repo with a single 'main' branch (one commit)."""
    bare = tmp_path / "origin.git"
    _git(["init", "-q", "--bare", str(bare)], tmp_path)

    seed = tmp_path / "seed"
    _git(["clone", "-q", str(bare), str(seed)], tmp_path)
    (seed / "app.txt").write_text("base\n", encoding="utf-8")
    _git(["checkout", "-q", "-b", "main"], seed)
    _git(["add", "."], seed)
    _git(["commit", "-qm", "init"], seed)
    _git(["push", "-q", "origin", "main"], seed)
    return f"file://{bare}"


@pytest.fixture
def repo(tmp_path, origin):
    """A grove repo created with the 'default' profile (base 'main').

    Returns (git_runner, repo_context).
    """
    cfg.apply_policy(cfg.resolve_profile("default"))
    git = GitRunner()
    ctx = core_setup.setup(
        git, origin, into=tmp_path / "work", name="repo",
        base_branch=cfg.DEFAULT_BASE,
    )
    return git, ctx
