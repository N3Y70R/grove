"""Unit tests for SSH URL parsing and host rewriting."""

from grove.core import sshalias


def test_url_host_scp_form():
    assert sshalias.url_host("git@github.com:org/repo.git") == "github.com"


def test_url_host_ssh_scheme():
    assert sshalias.url_host("ssh://git@github.com/org/repo.git") == "github.com"


def test_url_host_https_is_none():
    assert sshalias.url_host("https://github.com/org/repo.git") is None


def test_rewrite_host_scp_form():
    out = sshalias.rewrite_host("git@github.com:org/repo.git", "gh-work")
    assert out == "git@gh-work:org/repo.git"


def test_rewrite_host_ssh_scheme():
    out = sshalias.rewrite_host("ssh://git@github.com/org/repo.git", "gh-work")
    assert out == "ssh://git@gh-work/org/repo.git"


def test_rewrite_host_leaves_https_untouched():
    url = "https://github.com/org/repo.git"
    assert sshalias.rewrite_host(url, "gh-work") == url


# --- report_for_host (repo↔alias mapping) ------------------------------- #

_FAKE = {
    "github.com": {"hostname": "github.com"},
    "gh-work": {"hostname": "github.com", "identityfile": ["~/.ssh/id_work"]},
    "gh-perso": {"hostname": "github.com", "identityfile": ["~/.ssh/id_perso"]},
    "bb": {"hostname": "bitbucket.org"},
}


def _patch(monkeypatch):
    monkeypatch.setattr(sshalias, "list_config_hosts", lambda: list(_FAKE))
    monkeypatch.setattr(sshalias, "_ssh_g",
                        lambda h, echo=None: (_FAKE.get(h, {}), None if h in _FAKE else "err"))


def test_report_for_canonical_host_lists_aliases(monkeypatch):
    _patch(monkeypatch)
    rep = sshalias.report_for_host("github.com")
    assert rep.host == "github.com"
    assert rep.current is None
    assert {m.alias for m in rep.matches} == {"gh-work", "gh-perso"}


def test_report_for_alias_resolves_real_host_and_marks_current(monkeypatch):
    _patch(monkeypatch)
    rep = sshalias.report_for_host("gh-work")
    assert rep.host == "github.com"
    assert rep.current == "gh-work"
    assert {m.alias for m in rep.matches} == {"gh-work", "gh-perso"}
