"""Guards that the MCP tool surface stays *enriched* for agent discoverability.

Every tool parameter must carry a description, constrained choices must be
enums, and safety annotations must be set. These checks enforce the project
guideline: whenever a tool or parameter changes, keep the MCP schema enriched.

Skipped if the MCP SDK isn't installed (it's an optional extra).
"""

import asyncio

import pytest

pytest.importorskip("mcp")

from grove.mcp import server  # noqa: E402


def _tools():
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def test_all_tools_present():
    names = set(_tools())
    expected = {
        "grove_setup", "grove_list", "grove_create", "grove_track", "grove_remove",
        "grove_sync", "grove_publish", "grove_doctor", "grove_compare", "grove_config",
        "grove_ssh_check", "grove_ssh_add", "grove_ssh_accounts", "grove_ssh_doctor",
        "grove_ssh_remove",
    }
    assert expected <= names


def test_every_parameter_has_a_description():
    missing = []
    for name, t in _tools().items():
        for param, info in t.inputSchema.get("properties", {}).items():
            if not info.get("description"):
                missing.append(f"{name}.{param}")
    assert not missing, f"MCP params missing a description: {missing}"


def test_create_kind_is_an_enum():
    t = _tools()["grove_create"]
    assert t.inputSchema["properties"]["kind"].get("enum") == ["ticket", "release", "temp"]


def test_destructive_and_readonly_annotations():
    tools = _tools()
    for n in ("grove_remove", "grove_sync", "grove_publish", "grove_ssh_remove"):
        assert tools[n].annotations and tools[n].annotations.destructiveHint, n
    for n in ("grove_list", "grove_compare", "grove_ssh_check", "grove_ssh_accounts"):
        assert tools[n].annotations and tools[n].annotations.readOnlyHint, n
