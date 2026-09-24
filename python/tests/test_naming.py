"""Unit tests for the naming convention (slug, ticket extraction, classify)."""

from grove.core import naming


def test_slugify_basic():
    assert naming.slugify("Fix Login Bug") == "fix-login-bug"


def test_slugify_strips_accents():
    assert naming.slugify("Corrección Rápida") == "correccion-rapida"


def test_slugify_collapses_separators():
    assert naming.slugify("a/b  c__d!") == "a-b-c-d"


def test_slugify_empty():
    assert naming.slugify("  --!!  ") == ""


def test_extract_ticket_generic():
    assert naming.extract_ticket("feature/PROJ-123-thing") == "PROJ-123"


def test_extract_ticket_uppercases():
    assert naming.extract_ticket("proj-9") == "PROJ-9"


def test_extract_ticket_none():
    assert naming.extract_ticket("feature/cleanup") is None


def test_classify_special():
    assert naming.classify("temporary-unified-test", "temporary-unified-test").kind == "special"


def test_classify_base_wins_over_special():
    # module defaults: base = production, which is also listed as special
    assert naming.classify("production", "production").kind == "base"


def test_classify_temp():
    assert naming.classify("temp/quick", "temp/quick").kind == "temp"


def test_classify_release():
    c = naming.classify("release/v1.2.0", "release/v1.2.0")
    assert c.kind == "release"
    assert c.version == "v1.2.0"


def test_classify_ticket():
    c = naming.classify("feature/PROJ-1-x", "feature/PROJ-1-x")
    assert c.kind == "ticket"
    assert c.type == "feature"
    assert c.ticket == "PROJ-1"


def test_classify_unknown():
    assert naming.classify("chore/cleanup", "chore/cleanup").kind == "unknown"


def test_extract_ticket_ignores_version_numbers():
    # 'python-0.6.1' is a version, not ticket PYTHON-0.
    assert naming.extract_ticket("fix/python-0.6.1") is None
    assert naming.extract_ticket("release/v1.2.0") is None


def test_extract_ticket_still_matches_at_boundaries():
    assert naming.extract_ticket("feature/PROJ-123") == "PROJ-123"
    assert naming.extract_ticket("bugfix/PROJ-7-fix-login") == "PROJ-7"
