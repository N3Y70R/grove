"""Tests for the MCP operation layer (grove.mcp._ops).

These exercise the same logic the MCP tools expose, without importing the
MCP SDK. They reuse the integration ``repo`` fixture and pass ``cwd`` so the
repo is located independently of the process working directory.
"""

import shutil

import pytest

from grove.core.errors import UsageError
from grove.mcp import _ops


def test_op_list_includes_main(repo):
    _, ctx = repo
    res = _ops.op_list(cwd=str(ctx.root))
    rels = {w["rel_path"] for w in res["worktrees"]}
    assert "main" in rels
    assert res["count"] == len(res["worktrees"]) >= 1


def test_op_create_ticket(repo):
    _, ctx = repo
    res = _ops.op_create(kind="ticket", type="feature", name="Mcp Tool",
                         ticket="PROJ-7", cwd=str(ctx.root))
    assert res["rel_path"] == "feature/PROJ-7-mcp-tool"


def test_op_create_requires_fields(repo):
    _, ctx = repo
    with pytest.raises(UsageError):
        _ops.op_create(kind="ticket", cwd=str(ctx.root))


def test_op_create_unknown_kind(repo):
    _, ctx = repo
    with pytest.raises(UsageError):
        _ops.op_create(kind="bogus", name="x", cwd=str(ctx.root))


def test_op_track(repo):
    git, ctx = repo
    git.run(["branch", "feature/tracked", "main"], cwd=ctx.bare)
    res = _ops.op_track(branch="feature/tracked", cwd=str(ctx.root))
    assert res["rel_path"] == "feature/tracked"


def test_op_remove_requires_confirm(repo):
    _, ctx = repo
    _ops.op_create(kind="ticket", type="feature", name="todelete", cwd=str(ctx.root))
    with pytest.raises(UsageError):
        _ops.op_remove(target="feature/todelete", cwd=str(ctx.root))


def test_op_remove_with_confirm(repo):
    _, ctx = repo
    _ops.op_create(kind="ticket", type="feature", name="todelete", cwd=str(ctx.root))
    res = _ops.op_remove(target="feature/todelete", confirm=True, cwd=str(ctx.root))
    assert res["removed"] == ["feature/todelete"]
    rels = {w["rel_path"] for w in _ops.op_list(cwd=str(ctx.root))["worktrees"]}
    assert "feature/todelete" not in rels


def test_op_sync_requires_confirm(repo):
    _, ctx = repo
    with pytest.raises(UsageError):
        _ops.op_sync(target="main", cwd=str(ctx.root))


def test_op_config_show(repo):
    _, ctx = repo
    res = _ops.op_config_show(cwd=str(ctx.root))
    assert res["repo"] == "repo"
    assert res["default_base"] == "main"


def test_op_compare_in_sync(repo):
    _, ctx = repo
    _ops.op_create(kind="ticket", type="feature", name="cmp", cwd=str(ctx.root))
    res = _ops.op_compare(a="feature/cmp", b="main", cwd=str(ctx.root))
    assert res["status"] == "in sync"


# --------------------------------------------------------------------------- #
# SSH account provisioning ops (machine-level; redirected HOME).
# --------------------------------------------------------------------------- #

_HAS_SSH = shutil.which("ssh-keygen") is not None and shutil.which("git") is not None


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from grove.core import blockedit
    blockedit.reset_backup_cache()
    return tmp_path


@pytest.mark.skipif(not _HAS_SSH, reason="requires ssh-keygen and git")
def test_op_ssh_add_accounts_remove(home):
    (home / "dropi").mkdir()
    res = _ops.op_ssh_add("dropi-gh", host="github.com", email="x@dropi.co",
                          scope_dir=str(home / "dropi"), no_agent=True)
    assert res["pubkey"].startswith("ssh-ed25519 ")

    accts = _ops.op_ssh_accounts()
    assert accts["accounts"][0]["name"] == "dropi-gh"
    assert accts["accounts"][0]["routing"] == "ok"

    # doctor healthy (no auto-fixables)
    doc = _ops.op_ssh_doctor()
    assert doc["auto_fixable"] == 0

    # remove requires confirm
    with pytest.raises(UsageError):
        _ops.op_ssh_remove("dropi-gh")
    out = _ops.op_ssh_remove("dropi-gh", confirm=True)
    assert any("remove" in s for s in out["steps"])
    assert _ops.op_ssh_accounts()["accounts"] == []
