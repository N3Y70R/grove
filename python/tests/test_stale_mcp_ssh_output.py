"""0.14.1 — a clear error when grove was upgraded under a running MCP server,
and `gwt ssh add` / `gwt ssh accounts` output fixes."""

import asyncio
import shutil

import pytest

from grove.cli.main import main

needs_ssh = pytest.mark.skipif(shutil.which("ssh-keygen") is None or shutil.which("git") is None,
                               reason="requires ssh-keygen and git")


# --- stale MCP server --------------------------------------------------------- #

def test_stale_server_refuses_with_a_clear_message(monkeypatch):
    server = pytest.importorskip("grove.mcp.server")
    from mcp.server.mcpserver.exceptions import ToolError
    monkeypatch.setattr(server, "_installed_version", lambda: "99.0.0")
    with pytest.raises(ToolError, match=r"upgraded to 99\.0\.0.*restart the MCP client"):
        asyncio.run(server.mcp.call_tool("grove_repos", {"paths": ["/nonexistent"]}))


def test_matching_or_unknown_version_runs_normally(monkeypatch, tmp_path):
    server = pytest.importorskip("grove.mcp.server")
    import grove
    for v in (grove.__version__, None):
        monkeypatch.setattr(server, "_installed_version", lambda v=v: v)
        res = asyncio.run(server.mcp.call_tool("grove_repos", {"paths": [str(tmp_path)]}))
        assert not res.is_error


# --- gwt ssh ------------------------------------------------------------------ #

@pytest.fixture
def home(monkeypatch, tmp_path):
    from grove.core import blockedit
    from grove.core import platform as plat
    blockedit.reset_backup_cache()
    return plat.paths().home


@needs_ssh
def test_ssh_add_with_a_reused_key_does_not_demand_an_upload(home, capsys):
    import subprocess
    (home / ".ssh").mkdir(mode=0o700)
    key = home / ".ssh" / "id_ed25519_mine"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    (home / "me").mkdir()
    assert main(["ssh", "add", "me-gh", "--host", "github.com", "--key", str(key),
                 "--email", "me@example.com", "--scope-dir", str(home / "me"),
                 "--no-agent", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "Reused an existing key" in out and "isn't on github.com yet" in out
    assert "Upload this public key" not in out
    assert "gwt ssh check me-gh --live" in out


@needs_ssh
def test_ssh_add_with_a_new_key_asks_for_the_upload(home, capsys):
    (home / "me").mkdir()
    assert main(["ssh", "add", "me-gh", "--host", "github.com", "--email", "me@example.com",
                 "--scope-dir", str(home / "me"), "--no-passphrase", "--no-agent",
                 "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "Upload this public key to github.com" in out
    assert "gwt ssh check me-gh --live" in out


@needs_ssh
def test_ssh_accounts_columns_never_touch(home, capsys):
    for name, zone in (("a-gh", "work"), ("a-very-long-account-name", "personal-projects")):
        (home / zone).mkdir()
        assert main(["ssh", "add", name, "--host", "github.com",
                     "--key", str(home / ".ssh" / f"id_ed25519_{name}_github_long_suffix"),
                     "--email", f"{name}@example.com", "--scope-dir", str(home / zone),
                     "--no-passphrase", "--no-agent", "--no-color"]) == 0
    capsys.readouterr()
    assert main(["ssh", "accounts", "--no-color"]) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    header = lines[0]
    starts = [header.index(h) for h in ("HOST", "KEY", "ZONE", "ROUTING")]
    for line in lines[1:]:
        for s in starts:                       # every column starts after a blank
            assert line[s - 1] == " ", line
