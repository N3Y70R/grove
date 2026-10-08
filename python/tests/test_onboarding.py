"""Readiness boundaries using temporary destinations, never real client config."""
import json
from pathlib import Path
import pytest
from grove.core import onboarding as ob, skill
from grove.cli.main import main


@pytest.fixture(autouse=True)
def local_checks(monkeypatch):
    monkeypatch.setattr(ob, "_git_version", lambda: (True, "git version test"))


def test_first_install_and_repeat(tmp_path):
    root = tmp_path / "skills"
    assert ob.report(path=str(root))["verdict"] == "action_required"
    first = ob.report(path=str(root), install_skill=True)
    assert first["verdict"] == "ready_cli"
    assert first["installation"]["mode"] == "created"
    assert (root / "grove/references/signing.md").is_file()
    again = ob.report(path=str(root), install_skill=True)
    assert again["installation"]["mode"] == "unchanged"


def test_preview_no_writes_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "_latest_version", lambda: pytest.fail("network in preview"))
    result = ob.report(path=str(tmp_path / "skills"), install_skill=True, dry_run=True, check_update=True)
    assert result["installation"]["dry_run"]
    assert not (tmp_path / "skills").exists()
    assert any(c["status"] == "skipped" for c in result["checks"])


def test_edited_copy_preserved(tmp_path):
    ob.report(path=str(tmp_path), install_skill=True)
    p = tmp_path / "grove/SKILL.md"
    p.write_text(p.read_text() + "\ncustomized\n")
    result = ob.report(path=str(tmp_path), install_skill=True)
    assert result["verdict"] == "action_required"
    assert p.read_text().endswith("customized\n")


def test_missing_reference_detected_and_restored(tmp_path):
    ob.report(path=str(tmp_path), install_skill=True)
    p = tmp_path / "grove/references/signing.md"
    p.unlink()
    assert ob.report(path=str(tmp_path))["verdict"] == "action_required"
    assert ob.report(path=str(tmp_path), install_skill=True)["verdict"] == "ready_cli"
    assert p.is_file()


def test_cli_does_not_require_mcp(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "_mcp_available", lambda: pytest.fail("CLI tested MCP"))
    assert ob.report(path=str(tmp_path), install_skill=True)["verdict"] == "ready_cli"


@pytest.mark.parametrize("available,verdict", [(False, "problem"), (True, "pending_client")])
def test_mcp_not_claimed_connected(tmp_path, monkeypatch, available, verdict):
    monkeypatch.setattr(ob, "_mcp_available", lambda: available)
    result = ob.report(channel="mcp", client="cursor", path=str(tmp_path), install_skill=True)
    assert result["verdict"] == verdict
    assert any("grove_skill_status" in s for s in result["next_steps"])


def test_missing_git(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "_git_version", lambda: (False, "unavailable"))
    assert ob.report(path=str(tmp_path), install_skill=True)["verdict"] == "problem"


def test_unknown_client_informs(tmp_path):
    result = ob.report(client="future-client", path=str(tmp_path), install_skill=True)
    assert result["verdict"] == "action_required"


def test_update_inconclusive(tmp_path, monkeypatch):
    def unavailable():
        raise OSError("network")
    monkeypatch.setattr(ob, "_latest_version", unavailable)
    result = ob.report(path=str(tmp_path), install_skill=True, check_update=True)
    assert result["verdict"] == "ready_cli"
    assert any(c["status"] == "inconclusive" for c in result["checks"])


def test_project_destination(repo):
    _, context = repo
    result = ob.report(target="project", cwd=str(context.root / "main"), install_skill=True)
    assert result["verdict"] == "ready_cli"
    assert Path(result["installation"]["path"]).parent.name == "skills"


def test_optional_signing_without_repo(tmp_path):
    result = ob.report(path=str(tmp_path / "skills"), install_skill=True, signing=True, cwd=str(tmp_path))
    assert result["verdict"] == "action_required"
    assert any(c["name"] == "signing" for c in result["checks"])


def test_invalid_channel_cannot_write(tmp_path):
    from grove.core.errors import UsageError
    with pytest.raises(UsageError):
        ob.report(channel="unknown", path=str(tmp_path), install_skill=True)
    assert not (tmp_path / "grove").exists()


def test_cli_json_same_core_result(tmp_path, capsys):
    assert main(["onboard", "--path", str(tmp_path), "--install-skill", "--dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"]["installation"]["dry_run"]
    assert result["result"]["verdict"] == "action_required"


def test_optional_ssh_delegates_without_repairs(tmp_path, monkeypatch):
    from grove.core import sshdoctor
    calls = []
    monkeypatch.setattr(sshdoctor, "report", lambda **kw: calls.append(kw) or {"remaining_findings": [{"check": "example"}]})
    result = ob.report(path=str(tmp_path), install_skill=True, ssh=True)
    assert result["verdict"] == "action_required"
    assert calls == [{"fix": False, "dry_run": False, "interactive": False}]


def test_unverified_copy_needs_explicit_install(tmp_path):
    ob.report(path=str(tmp_path), install_skill=True)
    (tmp_path / "grove" / skill.MANIFEST).unlink()
    assert ob.report(path=str(tmp_path))["verdict"] == "action_required"
    assert ob.report(path=str(tmp_path), install_skill=True)["verdict"] == "ready_cli"


def test_missing_client_does_not_claim_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(ob.shutil, "which", lambda _: None)
    result = ob.report(client="codex", path=str(tmp_path), install_skill=True)
    check = next(c for c in result["checks"] if c["name"] == "client")
    assert check["status"] == "not_verified"
    assert "not detected" in check["message"]


def test_update_response_limits(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 1048577
            return b'x' * size
    monkeypatch.setattr(ob, "urlopen", lambda url, timeout: Response())
    with pytest.raises(ValueError):
        ob._latest_version()


def test_relative_destination_uses_explicit_context(tmp_path):
    result = ob.report(path="skills", cwd=str(tmp_path), install_skill=True)
    assert result["installation"]["path"] == str(tmp_path / "skills/grove")


def test_update_available_does_not_upgrade(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "_latest_version", lambda: "99.0.0")
    result = ob.report(path=str(tmp_path), install_skill=True, check_update=True)
    assert any(c["status"] == "available" for c in result["checks"])
    assert result["version"] == ob.__version__
    assert result["verdict"] == "ready_cli"


def test_project_outside_worktree_informs(tmp_path):
    result = ob.report(target="project", cwd=str(tmp_path))
    assert result["verdict"] == "action_required"
