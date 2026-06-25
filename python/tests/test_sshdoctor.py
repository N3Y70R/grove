"""Tests for the SSH/git multi-account diagnose & repair engine."""

import shutil

import pytest

from grove.core import blockedit, sshdoctor, sshprov
from grove.core import platform as plat
from grove.core.gitrunner import GitRunner

pytestmark = pytest.mark.skipif(
    shutil.which("ssh-keygen") is None or shutil.which("git") is None,
    reason="requires ssh-keygen and git",
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    blockedit.reset_backup_cache()
    return tmp_path


def _add(home, name="dropi-gh", host="github.com"):
    sshprov.add_account(sshprov.AddSpec(
        name=name, host=host, email="x@dropi.co", scope_dir=home / "dropi",
        no_passphrase=True, no_agent=True))


def _checks(findings):
    return {f.check for f in findings}


def test_healthy_after_add_has_no_fixables(home):
    (home / "dropi").mkdir()
    _add(home)
    findings = sshdoctor.diagnose()
    # No auto-fixable problems (useConfigOnly was set by add; block has IdentitiesOnly).
    assert [f for f in findings if f.severity == "fix"] == []


def test_detects_and_fixes_open_perms(home):
    (home / "dropi").mkdir()
    _add(home)
    key = home / ".ssh" / "id_ed25519_dropi_gh"
    key.chmod(0o644)
    findings = sshdoctor.diagnose()
    assert "perms" in _checks(findings)
    sshdoctor.apply_fixes(findings)
    assert plat.check_key_perms(key) is True


def test_detects_and_fixes_missing_identitiesonly(home):
    (home / "dropi").mkdir()
    _add(home)
    cfg = home / ".ssh" / "config"
    cfg.write_text(cfg.read_text().replace("    IdentitiesOnly yes\n", ""))
    findings = sshdoctor.diagnose()
    assert "identitiesonly" in _checks(findings)
    sshdoctor.apply_fixes(findings)
    assert "IdentitiesOnly yes" in (home / ".ssh" / "config").read_text()


def test_detects_and_fixes_useconfigonly(home):
    (home / "dropi").mkdir()
    _add(home)
    GitRunner().run(["config", "--global", "--unset", "user.useConfigOnly"], check=False)
    findings = sshdoctor.diagnose()
    assert "useconfigonly" in _checks(findings)
    sshdoctor.apply_fixes(findings)
    val = GitRunner().run(["config", "--global", "--get", "user.useConfigOnly"],
                          check=False, mutating=False).stdout.strip()
    assert val == "true"


def test_detects_and_fixes_missing_insteadof(home):
    (home / "dropi").mkdir()
    _add(home)
    ident = home / ".config" / "grove" / "identities" / "dropi.gitconfig"
    # Strip the url rewrite, leaving the account un-routed.
    ident.write_text("[user]\n    email = x@dropi.co\n")
    findings = sshdoctor.diagnose()
    assert "insteadof" in _checks(findings)
    sshdoctor.apply_fixes(findings)
    assert "git@dropi-gh:" in ident.read_text()


def test_detects_secret_in_url_rewrite(home):
    (home / "dropi").mkdir()
    _add(home)
    GitRunner().run(
        ["config", "--global",
         "url.https://victor:ATATT_token@bitbucket.org.insteadOf",
         "https://bitbucket.org"], check=False)
    findings = sshdoctor.diagnose()
    assert "secret" in _checks(findings)
    # report-only: no fixer
    secret = next(f for f in findings if f.check == "secret")
    assert secret.severity == "review" and secret.fixer is None


def test_detects_trap_real_host_without_block(home):
    # Alias-only account (no identity routing): real host bitbucket.org has neither a
    # Host block nor an insteadOf rewrite → canonical git@bitbucket.org: would fail.
    sshprov.add_account(sshprov.AddSpec(
        name="dropi-bb", host="bitbucket.org", no_identity=True,
        no_passphrase=True, no_agent=True))
    findings = sshdoctor.diagnose()
    trap = [f for f in findings if f.check == "trap"]
    assert trap and trap[0].target == "bitbucket.org"
    assert trap[0].severity == "review"


def test_no_trap_when_routing_ok(home):
    # With identity routing in place, canonical URLs are rewritten → no trap.
    (home / "dropi").mkdir()
    _add(home, name="dropi-bb", host="bitbucket.org")
    findings = sshdoctor.diagnose()
    assert "trap" not in _checks(findings)
