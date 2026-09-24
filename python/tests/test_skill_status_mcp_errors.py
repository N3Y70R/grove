"""0.16.0 — `gwt skill status` / `grove_skill_status` need no repo (FEEDBACK
§24, V1), and grove's own errors reach MCP clients with their text (V2)."""

import asyncio
import json
import re

import pytest

import grove
from grove.core import skill as core_skill


def _age(d, version="0.0.1"):
    p = d / "SKILL.md"
    p.write_text(re.sub(r'grove-version: "[^"]+"', f'grove-version: "{version}"',
                        p.read_text(encoding="utf-8")), encoding="utf-8")


# --- V1 ---------------------------------------------------------------------- #

def test_status_without_copies_says_how_to_install():
    res = core_skill.machine_status()
    assert res == {"version": grove.__version__, "skills": [], "hint": res["hint"]}
    assert "gwt skill install" in res["hint"]


def test_status_lists_both_user_copies_without_a_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                           # not a repo
    core_skill.install(dest_root=core_skill.target_root("agents"))
    core_skill.install(dest_root=core_skill.target_root("claude"))
    res = core_skill.machine_status()
    assert [(r["scope"], r["path"], r["outdated"], r["edited"]) for r in res["skills"]] == [
        ("agents", "~/.agents/skills/grove", False, False),
        ("claude", "~/.claude/skills/grove", False, False)]
    assert res["hint"] is None


def test_status_hints_follow_the_state():
    root = core_skill.target_root("agents")
    core_skill.install(dest_root=root)
    _age(root / "grove")
    core_skill._write_manifest(root / "grove", core_skill._files())      # untouched, old
    assert "refreshes them" in core_skill.machine_status()["hint"]
    _age(root / "grove", "0.0.2")                                         # now edited
    assert "--force" in core_skill.machine_status()["hint"]


def test_cli_skill_status(tmp_path, monkeypatch, capsys):
    from grove.cli.main import main
    monkeypatch.chdir(tmp_path)
    core_skill.install(dest_root=core_skill.target_root("claude"))
    assert main(["skill", "status", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)["result"]
    assert [r["scope"] for r in res["skills"]] == ["claude"]


# --- V2 ---------------------------------------------------------------------- #

def _call(name, args):
    server = pytest.importorskip("grove.mcp.server")
    return asyncio.run(server.mcp.call_tool(name, args))


def test_grove_errors_reach_the_client_with_their_text(tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match=r"No managed repo \(\.bare/\) found"):
        _call("grove_config", {"cwd": str(tmp_path)})
    with pytest.raises(ToolError, match=r"target 'project' needs a git worktree"):
        _call("grove_skill_install", {"target": "project", "cwd": str(tmp_path)})


def test_other_exceptions_stay_masked(monkeypatch):
    server = pytest.importorskip("grove.mcp.server")
    from mcp.server.mcpserver.exceptions import UnexpectedToolError

    def boom():
        raise RuntimeError("internal detail")
    monkeypatch.setattr(server._ops, "op_skill_status", boom)
    with pytest.raises(UnexpectedToolError) as info:
        _call("grove_skill_status", {})
    assert "internal detail" not in str(info.value)


def test_errors_arrive_as_text_over_the_protocol_handler(tmp_path):
    """What a client sees: an error result whose text is grove's message."""
    server = pytest.importorskip("grove.mcp.server")
    from mcp.types import CallToolRequestParams

    async def go():
        ctx = None
        return await server.mcp._handle_call_tool(
            ctx, CallToolRequestParams(name="grove_config", arguments={"cwd": str(tmp_path)}))
    try:
        res = asyncio.run(go())
    except Exception:                       # handler signature is SDK-internal
        pytest.skip("SDK handler not callable without a request context")
    assert res.is_error and "No managed repo" in res.content[0].text
