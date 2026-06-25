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
