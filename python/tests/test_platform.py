"""Unit tests for the OS layer (paths, perms, keychain, gitdir normalization)."""

import sys

import pytest

from grove.core import platform as plat


def test_paths_follow_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    p = plat.paths()
    assert p.home == tmp_path
    assert p.ssh_config == tmp_path / ".ssh" / "config"
    assert p.gitconfig == tmp_path / ".gitconfig"
    assert p.identities_dir == tmp_path / ".config" / "grove" / "identities"


def test_normalize_gitdir_absolute_forwardslash_trailing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    out = plat.normalize_gitdir("~/dropi")
    assert out.endswith("/")
    assert "\\" not in out
    assert out == (tmp_path / "dropi").as_posix() + "/"


def test_keychain_supported_tracks_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert plat.keychain_supported() is True
    monkeypatch.setattr(sys, "platform", "linux")
    assert plat.keychain_supported() is False
    monkeypatch.setattr(sys, "platform", "win32")
    assert plat.keychain_supported() is False


def test_ssh_defaults_block_usekeychain_only_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "UseKeychain yes" in plat.ssh_defaults_block()
    monkeypatch.setattr(sys, "platform", "linux")
    assert "UseKeychain yes" not in plat.ssh_defaults_block()
    assert "IdentitiesOnly yes" in plat.ssh_defaults_block()


def test_perms_na_on_windows(monkeypatch, tmp_path):
    f = tmp_path / "key"
    f.write_text("x")
    monkeypatch.setattr(sys, "platform", "win32")
    assert plat.check_key_perms(f) is None
    assert plat.enforce_key_perms(f) is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_perms_enforced_on_posix(tmp_path):
    f = tmp_path / "key"
    f.write_text("x")
    f.chmod(0o644)
    assert plat.check_key_perms(f) is False
    assert plat.enforce_key_perms(f) is True
    assert plat.check_key_perms(f) is True
