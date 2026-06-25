"""Unit tests for marker-scoped, idempotent, atomic dotfile edits."""

import pytest

from grove.core import blockedit
from grove.core.errors import ValidationError

BODY = "Host dropi-gh\n    HostName github.com\n    IdentityFile ~/.ssh/id_ed25519_dropi_gh"


def test_upsert_creates_region_into_empty():
    out = blockedit.upsert_block("", "account", "dropi-gh", BODY)
    assert "# >>> grove:account=dropi-gh >>>" in out
    assert "# <<< grove:account=dropi-gh <<<" in out
    assert "HostName github.com" in out
    assert out.endswith("\n")


def test_upsert_is_idempotent():
    once = blockedit.upsert_block("", "account", "dropi-gh", BODY)
    twice = blockedit.upsert_block(once, "account", "dropi-gh", BODY)
    assert once == twice


def test_upsert_updates_in_place_preserving_surroundings():
    base = "# my own comment\nHost example\n    User me\n"
    added = blockedit.upsert_block(base, "account", "x", "Host x\n    User git")
    # User content preserved verbatim at the top.
    assert added.startswith("# my own comment\nHost example\n    User me\n")
    # Update the body; surroundings must remain byte-identical.
    updated = blockedit.upsert_block(added, "account", "x", "Host x\n    User git\n    IdentitiesOnly yes")
    assert updated.startswith("# my own comment\nHost example\n    User me\n")
    assert "IdentitiesOnly yes" in updated
    assert updated.count("# >>> grove:account=x >>>") == 1


def test_find_blocks_returns_bodies():
    text = blockedit.upsert_block("", "account", "a", "Host a")
    text = blockedit.upsert_block(text, "zone", "dropi", "[user]\n    email = x@y.z")
    accounts = blockedit.find_blocks(text, "account")
    zones = blockedit.find_blocks(text, "zone")
    assert accounts == {"a": "Host a"}
    assert zones["dropi"].strip().startswith("[user]")


def test_remove_drops_only_its_region():
    base = "keep-top\n"
    text = blockedit.upsert_block(base, "account", "a", "Host a")
    text = blockedit.upsert_block(text, "account", "b", "Host b")
    new, removed = blockedit.remove_block(text, "account", "a")
    assert removed is True
    assert "grove:account=a" not in new
    assert "grove:account=b" in new
    assert new.startswith("keep-top\n")


def test_remove_absent_is_noop():
    new, removed = blockedit.remove_block("nothing here\n", "account", "ghost")
    assert removed is False
    assert new == "nothing here\n"


def test_unbalanced_marker_raises():
    broken = "# >>> grove:account=a >>>\nHost a\n"  # no close
    with pytest.raises(ValidationError):
        blockedit.upsert_block(broken, "account", "a", "Host a")


def test_write_atomic_leaves_no_tmp(tmp_path):
    target = tmp_path / "sub" / "config"
    blockedit.write_atomic(target, "hello\n")
    assert target.read_text() == "hello\n"
    assert not (tmp_path / "sub" / "config.grove-tmp").exists()


def test_backup_once_only_first_time(tmp_path):
    blockedit.reset_backup_cache()
    f = tmp_path / "config"
    f.write_text("original\n")
    backups = tmp_path / "backups"
    first = blockedit.backup_once(f, backups)
    second = blockedit.backup_once(f, backups)
    assert first is not None and first.exists()
    assert first.read_text() == "original\n"
    assert second is None  # cached; not backed up twice
