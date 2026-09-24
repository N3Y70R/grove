"""0.11.1 — typed MCP output schemas: the contract.

Calls every tool that has a typed output schema through the MCP server, on a
real repo, and checks that `structured_content` equals the JSON text. The SDK
silently DROPS keys the schema doesn't declare (and errors on a missing
required key), so any drift between a tool's result and its schema fails here.
"""

import asyncio
import json
import shutil
import subprocess

import pytest

pytest.importorskip("mcp")

from grove.mcp import server  # noqa: E402

TYPED = {"grove_setup", "grove_convert", "grove_list", "grove_create", "grove_track",
         "grove_start", "grove_fetch", "grove_remove", "grove_reset", "grove_sync",
         "grove_doctor", "grove_compare", "grove_config", "grove_publish",
         "grove_ssh_check", "grove_ssh_aliases", "grove_ssh_add", "grove_ssh_accounts",
         "grove_ssh_doctor", "grove_ssh_remove", "grove_skill_install", "grove_repos"}


def _git(args, cwd):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


def call(_tool, **args):
    res = asyncio.run(server.mcp.call_tool(_tool, args))
    assert not res.is_error, res
    text = json.loads(res.content[0].text)
    assert res.structured_content == text, (
        f"{_tool}: structured result differs from the text (undeclared or mistyped keys?)")
    return text


def _schemas():
    return {t.name: t.output_schema for t in asyncio.run(server.mcp.list_tools())}


def test_typed_tools_publish_detailed_schemas():
    schemas = _schemas()
    for name in TYPED:
        props = schemas[name].get("properties") or {}
        assert props, f"{name}: output schema has no properties"
        undocumented = [p for p, s in props.items() if not s.get("description")]
        assert undocumented == [], f"{name}: fields without description: {undocumented}"


def test_every_typed_tool_honours_its_schema(repo, origin, tmp_path):
    git, ctx = repo
    cwd = str(ctx.root)
    mate = tmp_path / "mate"
    _git(["clone", "-q", origin, str(mate)], tmp_path)
    for b in ("feature/PROJ-7-pay", "hotfix/PROJ-9-fix"):
        _git(["checkout", "-q", "-b", b], mate)
        (mate / b.replace("/", "_")).write_text("x\n", encoding="utf-8")
        _git(["add", "."], mate)
        _git(["commit", "-qm", b], mate)
        _git(["push", "-q", "origin", b], mate)

    assert call("grove_fetch", cwd=cwd, prune=True)["prune"] is True
    assert call("grove_start", cwd=cwd, type="feature", name="login", ticket="PROJ-1")["mode"] == "created"
    assert call("grove_start", cwd=cwd, type="feature", name="x", ticket="PROJ-1")["mode"] == "existing"
    assert call("grove_start", cwd=cwd, type="feature", name="x", ticket="PROJ-7")["mode"] == "resumed"
    call("grove_create", cwd=cwd, kind="ticket", type="feature", name="two", ticket="PROJ-2")
    call("grove_create", cwd=cwd, kind="temp", name="spike")
    assert call("grove_track", cwd=cwd, branch="hotfix/PROJ-9-fix")["warnings"] == []
    rows = call("grove_list", cwd=cwd)["worktrees"]
    assert {r["kind"] for r in rows} >= {"base", "ticket", "temp"}
    call("grove_doctor", cwd=cwd)
    assert call("grove_compare", cwd=cwd, a="main")["status"] == "in sync"
    assert call("grove_compare", cwd=cwd, vs="main")["rows"]
    assert call("grove_remove", cwd=cwd, merged=True, dry_run=True)["dry_run"] is True
    assert call("grove_remove", cwd=cwd, target="temp/spike", confirm=True)["mode"] == "single"
    assert call("grove_reset", cwd=cwd, target="main", confirm=True)["worktree"] == "main"
    assert call("grove_sync", cwd=cwd, target="main", confirm=True)["deprecated"] == "use grove_reset"

    new = call("grove_setup", url=origin, into=str(tmp_path / "other"), name="r2",
               profile="personal")
    assert new["profile"] == "personal"
    clone = tmp_path / "plain"
    _git(["clone", "-q", origin, str(clone)], tmp_path)
    assert call("grove_convert", path=str(clone), dry_run=True)["dry_run"] is True
    assert call("grove_convert", path=str(clone), fetch=False)["into"] is False


def test_every_tool_is_typed():
    schemas = _schemas()
    assert TYPED == set(schemas), f"untyped or unknown: {set(schemas) ^ TYPED}"


def test_config_and_publish_honour_their_schemas(repo):
    git, ctx = repo
    cwd = str(ctx.root)
    shown = call("grove_config", cwd=cwd)
    assert shown["default_base"] == "main" and "release" in shown
    assert call("grove_config", cwd=cwd, set_key="default_base", set_value="main")["key"] == "default_base"
    assert call("grove_config", cwd=cwd, set_key="allowed_types", set_value="feature,fix")["value"] == ["feature", "fix"]
    assert call("grove_config", cwd=cwd, set_key="relative_worktrees", set_value="false")["applied"] is None
    assert call("grove_config", cwd=cwd, unset_key="allowed_types")["unset"] == "allowed_types"
    assert call("grove_config", cwd=cwd, set_ssh_alias="none")["ssh_alias"] == ""
    pub = call("grove_publish", cwd=cwd, into="integration", regenerate=True, base="main")
    assert pub["mode"] == "created" and pub["created"] is True


@pytest.fixture
def ssh_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    from grove.core import blockedit
    blockedit.reset_backup_cache()
    return home


@pytest.mark.skipif(not (shutil.which("ssh-keygen") and shutil.which("git")),
                    reason="requires ssh-keygen and git")
def test_ssh_tools_honour_their_schemas(ssh_home):
    zone = ssh_home / "work"
    zone.mkdir()
    assert call("grove_ssh_add", name="t-gh", host="github.com", email="t@example.com",
                scope_dir=str(zone), dry_run=True)["dry_run"] is True
    added = call("grove_ssh_add", name="t-gh", host="github.com", email="t@example.com",
                 scope_dir=str(zone), no_agent=True)
    assert added["pubkey"].startswith("ssh-ed25519 ")
    accts = call("grove_ssh_accounts")
    assert accts["accounts"][0]["routing"] == "ok"
    assert call("grove_ssh_check", target="t-gh")["hosts"][0]["target"] == "t-gh"
    assert call("grove_ssh_check", all=True)["hosts"]
    # `ssh -G` reads the passwd home, not $HOME, so the alias match itself is
    # covered elsewhere; here only the result's shape/contract matters.
    assert isinstance(call("grove_ssh_aliases", target="github.com")["aliases"], list)
    assert "findings" in call("grove_ssh_doctor")
    assert call("grove_ssh_remove", name="t-gh", dry_run=True)["dry_run"] is True
    assert call("grove_ssh_remove", name="t-gh", confirm=True)["name"] == "t-gh"


def test_skill_install_honours_its_schema(tmp_path):
    res = call("grove_skill_install", path=str(tmp_path / "skills"), dry_run=True)
    assert res["mode"] == "created" and res["dry_run"] is True


def test_repos_honours_its_schema(repo, tmp_path):
    git, ctx = repo
    res = call("grove_repos", paths=[str(ctx.root.parent)])
    assert res["source"] == "paths" and res["count"] >= 1
    assert str(ctx.root) in [r["path"] for r in res["repos"]]
    empty = call("grove_repos")                    # no zones in the test home
    assert empty["source"] == "default" and empty["roots"] == [] and empty["hint"]
