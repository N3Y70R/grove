"""Unit tests for the policy/config layer (profiles, ticket patterns, serialization)."""

from grove.core import config


def test_resolve_default_profile():
    p = config.resolve_profile("default")
    assert p["default_base"] == "main"
    assert p["tickets"] == "optional"


def test_apply_default_profile():
    config.apply_policy(config.resolve_profile("default"))
    assert config.DEFAULT_BASE == "main"
    assert "feature" in config.TICKET_TYPES
    # 'release' is always available but is never a ticket type.
    assert config.RELEASE_TYPE not in config.TICKET_TYPES


def test_apply_gitflow_profile():
    config.apply_policy(config.resolve_profile("gitflow"))
    assert config.TICKETS == "required"
    assert config.INTEGRATION_BRANCH == "develop"
    assert "develop" in config.SPECIAL_WORKTREES


def test_pattern_from_prefixes_uppercases_and_joins():
    assert config._pattern_from_prefixes(["proj", "ops"]) == r"(?:PROJ|OPS)-\d+"


def test_pattern_from_prefixes_falls_back_when_empty():
    assert config._pattern_from_prefixes([]) == r"[A-Z][A-Z0-9]+-\d+"


def test_ticket_prefixes_restrict_matches():
    config.apply_policy({"ticket_prefixes": ["PROJ"]})
    assert config.TICKET_RE.search("PROJ-1")
    assert not config.TICKET_RE.search("OPS-1")


def test_env_prefix_overrides_pattern(monkeypatch):
    monkeypatch.setenv("GROVE_TICKET_PREFIX", "API")
    config.apply_policy({})  # recompute, honoring the env override
    assert config.TICKET_RE.search("API-7")
    assert not config.TICKET_RE.search("PROJ-7")


def test_effective_policy_roundtrip_renders_toml():
    config.apply_policy(config.resolve_profile("gitflow"))
    pol = config.effective_policy()
    assert pol["default_base"] == "main"
    assert pol["tickets"] == "required"

    text = config.render_repo_config(pol)
    assert 'tickets = "required"' in text
    assert "[release]" in text
