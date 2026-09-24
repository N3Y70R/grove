"""0.11.1 — typed MCP output schemas: the contract.

Calls every tool that has a typed output schema through the MCP server, on a
real repo, and checks that `structured_content` equals the JSON text. The SDK
silently DROPS keys the schema doesn't declare (and errors on a missing
required key), so any drift between a tool's result and its schema fails here.
"""

import asyncio
import json
import subprocess

import pytest

pytest.importorskip("mcp")

from grove.mcp import server  # noqa: E402

TYPED = {"grove_setup", "grove_convert", "grove_list", "grove_create", "grove_track",
         "grove_start", "grove_fetch", "grove_remove", "grove_reset", "grove_sync",
         "grove_doctor", "grove_compare"}


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
