"""CLI-level tests for the `gwt ssh` write commands (add / accounts / remove)."""

import json
import shutil

import pytest

from grove.cli.main import main

pytestmark = pytest.mark.skipif(
    shutil.which("ssh-keygen") is None or shutil.which("git") is None,
    reason="requires ssh-keygen and git",
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from grove.core import blockedit
    blockedit.reset_backup_cache()
    return tmp_path


def test_add_then_remove_via_cli(home, capsys):
    (home / "dropi").mkdir()
    rc = main(["ssh", "add", "dropi-gh", "--host", "github.com",
               "--email", "x@dropi.co", "--scope-dir", str(home / "dropi"),
               "--no-passphrase", "--no-agent", "--no-color"])
    assert rc == 0
    assert "Host dropi-gh" in (home / ".ssh" / "config").read_text()

    rc = main(["ssh", "remove", "dropi-gh", "--no-color"])
    assert rc == 0
    assert "Host dropi-gh" not in (home / ".ssh" / "config").read_text()
    # key kept by default
    assert (home / ".ssh" / "id_ed25519_dropi_gh").is_file()


def test_accounts_json(home, capsys):
    (home / "dropi").mkdir()
    main(["ssh", "add", "dropi-gh", "--host", "github.com", "--email", "x@dropi.co",
          "--scope-dir", str(home / "dropi"), "--no-passphrase", "--no-agent"])
    capsys.readouterr()
    rc = main(["ssh", "accounts", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    accounts = payload["result"]["accounts"]
    assert accounts[0]["name"] == "dropi-gh"
    assert accounts[0]["routing"] == "ok"


def test_add_json_requires_no_passphrase(home, capsys):
    (home / "dropi").mkdir()
    rc = main(["ssh", "add", "dropi-gh", "--host", "github.com", "--json"])
    assert rc == 3  # UsageError
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"


def test_remove_unknown_account_errors(home, capsys):
    rc = main(["ssh", "remove", "ghost", "--no-color"])
    assert rc == 1  # ValidationError
