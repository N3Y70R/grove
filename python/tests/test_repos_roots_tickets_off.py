"""0.14.0 — `repos_roots` for `gwt repos` (FEEDBACK #37) and no ticket
extraction when `tickets = "off"` (FEEDBACK §16)."""

import json

from grove.core import config as cfg
from grove.core import naming
from grove.core import platform as plat
from grove.core import repos as core_repos
from grove.core import start as core_start


def _user_config(text):
    p = plat.paths().home / ".config" / "grove" / "config.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# --- #37: repos_roots -------------------------------------------------------- #

def test_config_roots_reads_existing_folders(tmp_path):
    home = plat.paths().home
    (home / "code").mkdir()
    extra = tmp_path / "elsewhere"
    extra.mkdir()
    _user_config(f'repos_roots = ["~/code", "{extra}", "~/missing", "code"]\n')
    assert core_repos.config_roots() == [home / "code", extra]     # deduped, missing skipped


def test_config_roots_tolerates_a_string_or_no_file():
    assert core_repos.config_roots() == []
    (plat.paths().home / "code").mkdir()
    _user_config('repos_roots = "~/code"\n')
    assert core_repos.config_roots() == [plat.paths().home / "code"]
    _user_config('repos_roots = ["~/code"\n')                       # broken TOML: ignored
    assert core_repos.config_roots() == []


def test_discover_adds_repos_roots_to_the_zones(repo, monkeypatch):
    git, ctx = repo
    zone = plat.paths().home / "zone"
    zone.mkdir()
    monkeypatch.setattr(core_repos, "zone_roots", lambda: [zone])
    _user_config(f'repos_roots = ["{ctx.root.parent}", "{zone}"]\n')
    res = core_repos.discover()
    assert res["source"] == "default"
    assert res["roots"] == [str(zone), str(ctx.root.parent)]        # zones first, no duplicates
    assert str(ctx.root) in [r["path"] for r in res["repos"]]
    # explicit paths replace the defaults
    assert core_repos.discover([str(zone)])["repos"] == []


def test_hint_mentions_repos_roots_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(core_repos, "zone_roots", lambda: [])
    res = core_repos.discover()
    assert res["roots"] == [] and "repos_roots" in res["hint"]


def test_cli_repos_uses_repos_roots(repo, capsys):
    from grove.cli.main import main
    git, ctx = repo
    _user_config(f'repos_roots = ["{ctx.root.parent}"]\n')
    assert main(["repos", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)["result"]
    assert str(ctx.root) in [r["path"] for r in res["repos"]]


# --- §16: tickets = "off" ---------------------------------------------------- #

def test_no_ticket_is_read_when_tickets_are_off():
    cfg.TICKETS = "optional"
    assert naming.classify("feature/abc-12-login", "feature/abc-12-login").ticket == "ABC-12"
    cfg.TICKETS = "off"
    c = naming.classify("feature/abc-12-login", "feature/abc-12-login")
    assert c.kind == "ticket" and c.type == "feature" and c.ticket is None
    assert naming.ticket_of("feature/ABC-12-login") is None
    assert naming.extract_ticket("ABC-12") == "ABC-12"               # raw parsing unchanged


def test_list_and_start_report_no_ticket_when_off(repo):
    from grove.core.model import list_worktrees
    git, ctx = repo
    cfg.TICKETS = "off"
    res = core_start.start(git, ctx, type="feature", name="abc 12 login", fetch=False)
    assert res["branch"] == "feature/abc-12-login" and res["ticket"] is None
    row = next(w for w in list_worktrees(git, ctx) if w.branch == "feature/abc-12-login")
    assert naming.classify(row.rel_path, row.branch).ticket is None
