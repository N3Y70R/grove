"""Integration tests for the write path: add_account / remove_account.

Uses a redirected HOME and real ssh-keygen + git config (no network).
"""

import shutil

import pytest

from grove.core import blockedit, sshprov
from grove.core import platform as plat
from grove.core.errors import ValidationError
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


def _spec(name, **kw):
    kw.setdefault("no_passphrase", True)
    kw.setdefault("no_agent", True)
    return sshprov.AddSpec(name=name, **kw)


def test_add_full_account_writes_everything(home):
    spec = _spec("dropi-gh", host="github.com",
                 email="victor.orobio@dropi.co", scope_dir=home / "dropi")
    res = sshprov.add_account(spec)

    # Key generated + correct perms.
    key = home / ".ssh" / "id_ed25519_dropi_gh"
    assert key.is_file() and (home / ".ssh" / "id_ed25519_dropi_gh.pub").is_file()
    assert plat.check_key_perms(key) is True

    # SSH config: defaults + account block, IdentitiesOnly present.
    cfg = (home / ".ssh" / "config").read_text()
    assert "Host *" in cfg
    assert "Host dropi-gh" in cfg and "HostName github.com" in cfg
    assert "IdentitiesOnly yes" in cfg

    # Git identity: includeIf + identity file + hardening.
    gitcfg = (home / ".gitconfig").read_text()
    assert "grove:zone=dropi" in gitcfg and "gitdir:" in gitcfg
    ident = (home / ".config" / "grove" / "identities" / "dropi.gitconfig").read_text()
    assert "victor.orobio@dropi.co" in ident
    assert 'git@dropi-gh:' in ident and "insteadOf = git@github.com:" in ident

    useconfigonly = GitRunner().run(
        ["config", "--global", "--get", "user.useConfigOnly"],
        check=False, mutating=False).stdout.strip()
    assert useconfigonly == "true"

    # Inventory reflects it with coherent routing.
    inv = sshprov.read_inventory(plat.paths())
    acc = next(a for a in inv.accounts if a.name == "dropi-gh")
    assert inv.routing_state(acc) == "ok"
    assert res["pubkey"].startswith("ssh-ed25519 ")


def test_add_is_idempotent(home):
    spec = _spec("dropi-gh", host="github.com",
                 email="x@dropi.co", scope_dir=home / "dropi")
    sshprov.add_account(spec)
    cfg1 = (home / ".ssh" / "config").read_text()
    sshprov.add_account(spec)
    cfg2 = (home / ".ssh" / "config").read_text()
    assert cfg1 == cfg2
    assert cfg2.count("Host dropi-gh") == 1


def test_two_accounts_share_a_zone(home):
    sshprov.add_account(_spec("dropi-gh", host="github.com",
                              email="x@dropi.co", scope_dir=home / "dropi"))
    sshprov.add_account(_spec("dropi-bb", host="bitbucket.org",
                              email="x@dropi.co", scope_dir=home / "dropi"))
    ident = (home / ".config" / "grove" / "identities" / "dropi.gitconfig").read_text()
    assert "git@dropi-gh:" in ident and "git@dropi-bb:" in ident
    inv = sshprov.read_inventory(plat.paths())
    assert len(inv.zones) == 1
    assert inv.zones[0].rewrites == {"github.com": "dropi-gh", "bitbucket.org": "dropi-bb"}


def test_dry_run_writes_nothing(home):
    spec = _spec("dropi-gh", host="github.com",
                 email="x@dropi.co", scope_dir=home / "dropi", dry_run=True)
    sshprov.add_account(spec)
    assert not (home / ".ssh" / "config").exists()
    assert not (home / ".ssh" / "id_ed25519_dropi_gh").exists()


def test_no_identity_skips_gitconfig(home):
    spec = _spec("personal-gh", host="github.com", no_identity=True)
    sshprov.add_account(spec)
    assert "Host personal-gh" in (home / ".ssh" / "config").read_text()
    assert not (home / ".gitconfig").exists()


def test_identity_requires_email(home):
    with pytest.raises(ValidationError):
        sshprov.add_account(_spec("dropi-gh", host="github.com", scope_dir=home / "dropi"))


def test_invalid_name_rejected(home):
    with pytest.raises(ValidationError):
        sshprov.add_account(_spec("bad name!", host="github.com", no_identity=True))


def test_remove_account_cleans_block_and_zone(home):
    sshprov.add_account(_spec("dropi-gh", host="github.com",
                              email="x@dropi.co", scope_dir=home / "dropi"))
    sshprov.remove_account("dropi-gh", paths=plat.paths())
    cfg = (home / ".ssh" / "config").read_text()
    assert "Host dropi-gh" not in cfg
    # Zone became empty → includeIf + identity file gone.
    assert "grove:zone=dropi" not in (home / ".gitconfig").read_text()
    assert not (home / ".config" / "grove" / "identities" / "dropi.gitconfig").exists()
    # Key kept by default.
    assert (home / ".ssh" / "id_ed25519_dropi_gh").is_file()
