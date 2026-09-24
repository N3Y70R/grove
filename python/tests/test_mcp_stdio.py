"""End-to-end: start `python -m grove.mcp` over stdio (as an MCP client such as
Claude Desktop does), initialize, list the tools and call one for real.

Skipped if the MCP SDK isn't installed (it's an optional extra).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

import grove  # noqa: E402

SRC = str(Path(__file__).resolve().parents[1] / "src")


async def _session_roundtrip(repo_root: str):
    env = {**os.environ, "PYTHONPATH": SRC + os.pathsep + os.environ.get("PYTHONPATH", "")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "grove.mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("grove_config", {"cwd": repo_root})
            return init, tools, result


def test_server_speaks_mcp_over_stdio(repo):
    git, ctx = repo
    init, tools, result = asyncio.run(asyncio.wait_for(_session_roundtrip(str(ctx.root)), 60))

    assert init.server_info.name == "grove"
    names = {t.name for t in tools.tools}
    assert {"grove_list", "grove_fetch", "grove_reset", "grove_doctor", "grove_config"} <= names

    assert not result.is_error
    # Tools return dicts; like mcp 1.x, they arrive as JSON in a text block.
    data = json.loads(result.content[0].text)
    assert data["version"] == grove.__version__
    assert data["default_base"] == "main"
