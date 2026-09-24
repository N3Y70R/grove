"""0.7.0 — safer destructive operations: `reset` (ex-`sync`), `merged` in list,
`dry_run` for MCP remove, and empty type folders cleaned after remove."""

import json
import subprocess

import pytest

from grove.core import create
from grove.core.errors import UsageError
from grove.core.model import list_worktrees


def _git(args, cwd):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


def _commit(wt_path, name="f.txt", msg="work"):
    (wt_path / name).write_text(msg + "\n", encoding="utf-8")
    _git(["add", name], wt_path)
    _git(["commit", "-qm", msg], wt_path)


def _new_ticket(git, ctx, ticket="PROJ-1", name="login"):
    return create.create_ticket(git, ctx, type="feature", name=name, ticket=ticket)


def _row(git, ctx, rel):
    return next(w for w in list_worktrees(git, ctx) if w.rel_path == rel)


# --------------------------------------------------------------------------- #
# reset (formerly sync)
# --------------------------------------------------------------------------- #

def test_cli_reset_discards_local_commit(repo, capsys, monkeypatch):
    from grove.cli.main import main
    git, ctx = repo
    wt = ctx.root / "main"
    before = _git(["rev-parse", "HEAD"], wt)
    _commit(wt, msg="local only")
    monkeypatch.chdir(ctx.root)
    assert main(["reset", "main", "--yes", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["discarded"] == ["1 local commit(s) not pushed"]
    assert _git(["rev-parse", "HEAD"], wt) == before


def test_cli_sync_still_works_but_warns(repo, capsys, monkeypatch):
    from grove.cli.main import main
    git, ctx = repo
    monkeypatch.chdir(ctx.root)
    assert main(["sync", "main", "--yes"]) == 0
    out = capsys.readouterr()
    assert "deprecated" in (out.out + out.err).lower()
    assert "gwt reset" in (out.out + out.err)


def test_mcp_op_reset_and_deprecated_sync(repo):
    from grove.mcp import _ops
    git, ctx = repo
    with pytest.raises(UsageError):
        _ops.op_reset(target="main", cwd=str(ctx.root))          # needs confirm
    res = _ops.op_reset(target="main", confirm=True, cwd=str(ctx.root))
    assert res["worktree"] == "main"
    res = _ops.op_sync(target="main", confirm=True, cwd=str(ctx.root))
    assert res.get("deprecated") == "use grove_reset"


# --------------------------------------------------------------------------- #
# merged in list
# --------------------------------------------------------------------------- #

def test_list_merged_field(repo):
    git, ctx = repo
    path = _new_ticket(git, ctx)
    rel = "feature/PROJ-1-login"
    assert _row(git, ctx, "main").merged is None           # the base itself
    _commit(path, msg="feature work")
    assert _row(git, ctx, rel).merged is False             # has its own commit
    _git(["merge", "-q", "--ff-only", "feature/PROJ-1-login"], ctx.root / "main")
    assert _row(git, ctx, rel).merged is True              # now contained in base


def test_list_merged_in_cli_json_and_table(repo, capsys, monkeypatch):
    from grove.cli.main import main
    git, ctx = repo
    path = _new_ticket(git, ctx)
    _commit(path)
    _git(["merge", "-q", "--ff-only", "feature/PROJ-1-login"], ctx.root / "main")
    monkeypatch.chdir(ctx.root)
    main(["list", "--json"])
    rows = json.loads(capsys.readouterr().out)["result"]
    assert next(r for r in rows if r["rel_path"] == "feature/PROJ-1-login")["merged"] is True
    main(["list"])
    table = capsys.readouterr().out
    line = next(l for l in table.splitlines() if l.startswith("feature/PROJ-1-login"))
    assert "merged" in line


# --------------------------------------------------------------------------- #
# dry_run for MCP remove
# --------------------------------------------------------------------------- #

def test_mcp_remove_dry_run_needs_no_confirm_and_changes_nothing(repo):
    from grove.mcp import _ops
    git, ctx = repo
    path = _new_ticket(git, ctx)
    _commit(path)
    _git(["merge", "-q", "--ff-only", "feature/PROJ-1-login"], ctx.root / "main")

    res = _ops.op_remove(merged=True, dry_run=True, cwd=str(ctx.root))
    assert res["dry_run"] is True
    assert res["removed"] == ["feature/PROJ-1-login"]       # what WOULD go
    assert path.is_dir()                                    # nothing happened

    res = _ops.op_remove(target="PROJ-1", dry_run=True, cwd=str(ctx.root))
    assert res["dry_run"] is True and path.is_dir()


def test_mcp_remove_still_requires_confirm_without_dry_run(repo):
    from grove.mcp import _ops
    git, ctx = repo
    _new_ticket(git, ctx)
    with pytest.raises(UsageError):
        _ops.op_remove(target="PROJ-1", cwd=str(ctx.root))


# --------------------------------------------------------------------------- #
# empty type folders
# --------------------------------------------------------------------------- #

def test_remove_cleans_empty_type_folder(repo):
    from grove.core import remove as core_remove
    git, ctx = repo
    _new_ticket(git, ctx)
    wt = core_remove.resolve_target(git, ctx, "PROJ-1")
    core_remove.remove_one(git, ctx, wt)
    assert not (ctx.root / "feature").exists()
    assert (ctx.root / "main").is_dir() and (ctx.root / ".bare").is_dir()


def test_remove_keeps_type_folder_with_siblings(repo):
    from grove.core import remove as core_remove
    git, ctx = repo
    _new_ticket(git, ctx, "PROJ-1", "one")
    _new_ticket(git, ctx, "PROJ-2", "two")
    core_remove.remove_one(git, ctx, core_remove.resolve_target(git, ctx, "PROJ-1"))
    assert (ctx.root / "feature" / "PROJ-2-two").is_dir()


def test_remove_dry_run_keeps_type_folder(repo):
    from grove.core import remove as core_remove
    from grove.core.gitrunner import GitRunner
    git, ctx = repo
    _new_ticket(git, ctx)
    wt = core_remove.resolve_target(git, ctx, "PROJ-1")
    core_remove.remove_one(GitRunner(dry_run=True), ctx, wt)
    assert (ctx.root / "feature" / "PROJ-1-login").is_dir()
