"""0.8.2 — the repo remembers its profile: `unset` falls back to the repo's
profile, not to grove's internal (work-style) defaults."""

import pytest

from grove.core import config as cfg

from conftest import _CFG_NAMES  # the globals a policy touches


@pytest.fixture
def pristine():
    """Module state as a brand-new `gwt` process sees it."""
    snap = {n: getattr(cfg, n) for n in _CFG_NAMES}

    def restore():
        for n, v in snap.items():
            setattr(cfg, n, v)
    return restore


def _make_repo_config(tmp_path, profile):
    bare = tmp_path / ".bare"
    bare.mkdir()
    cfg.apply_policy(cfg.resolve_profile(profile))
    cfg.write_repo_config(bare, cfg.effective_policy())
    return bare


def test_grove_toml_records_the_profile(tmp_path):
    bare = _make_repo_config(tmp_path, "personal")
    assert 'profile = "personal"' in (bare / "grove.toml").read_text()


def test_unset_falls_back_to_the_repo_profile(tmp_path, pristine):
    bare = _make_repo_config(tmp_path, "personal")
    cfg.unset_repo_value(bare, "default_base")
    cfg.unset_repo_value(bare, "tickets")
    pristine()                                   # next gwt invocation
    cfg.load(bare)
    assert cfg.DEFAULT_BASE == "main"            # personal, not internal 'production'
    assert cfg.TICKETS == "optional"             # personal, not internal 'required'


def test_repo_values_still_override_the_profile(tmp_path, pristine):
    bare = _make_repo_config(tmp_path, "personal")
    cfg.set_repo_value(bare, "default_base", "develop")
    pristine()
    cfg.load(bare)
    assert cfg.DEFAULT_BASE == "develop"


def test_old_config_without_profile_uses_default_profile(tmp_path, pristine):
    bare = tmp_path / ".bare"
    bare.mkdir()
    (bare / "grove.toml").write_text('allowed_types = ["feature"]\n', encoding="utf-8")
    pristine()
    cfg.load(bare)
    assert cfg.DEFAULT_BASE == "main"            # 'default' profile
    assert cfg.TICKET_TYPES == ("feature",)


def test_unknown_profile_in_config_falls_back_without_crashing(tmp_path, pristine):
    bare = tmp_path / ".bare"
    bare.mkdir()
    (bare / "grove.toml").write_text('profile = "gone"\ndefault_base = "trunk"\n', encoding="utf-8")
    pristine()
    cfg.load(bare)
    assert cfg.DEFAULT_BASE == "trunk"
    assert cfg.TICKETS == "optional"             # from the 'default' profile
