"""0.8.3 — `gwt fetch`: bring remote changes and show where each worktree stands,
without ever touching the worktrees."""

import json
import subprocess

import pytest

from grove.core import fetch as core_fetch


def _git(args, cwd):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def remote_moved(repo, origin, tmp_path):
    """Someone else pushed a new commit to origin/main."""
    git, ctx = repo
    other = tmp_path / "other"
    _git(["clone", "-q", origin, str(other)], tmp_path)
    (other / "new.txt").write_text("from a teammate\n", encoding="utf-8")
    _git(["add", "."], other)
    _git(["commit", "-qm", "teammate"], other)
    _git(["push", "-q", "origin", "HEAD:main"], other)
    return git, ctx, other


def _row(rows, rel):
    return next(r for r in rows if r["worktree"] == rel)


def test_fetch_reports_behind_and_does_not_touch_worktrees(remote_moved):
    git, ctx, _ = remote_moved
    wt = ctx.root / "main"
    head = _git(["rev-parse", "HEAD"], wt)
    rows = core_fetch.fetch(git, ctx)
    main = _row(rows, "main")
    assert (main["ahead"], main["behind"]) == (0, 1)
    assert main["compared_to"] == "origin/main"
    assert main["status"] == "behind"
    assert _git(["rev-parse", "HEAD"], wt) == head        # untouched
    assert not (wt / "new.txt").exists()


def test_fetch_prune_removes_deleted_remote_branches(remote_moved):
    git, ctx, other = remote_moved
    _git(["push", "-q", "origin", "HEAD:refs/heads/tmp-x"], other)
    core_fetch.fetch(git, ctx)
    assert git.ok(["rev-parse", "--verify", "-q", "refs/remotes/origin/tmp-x"], cwd=ctx.bare)
    _git(["push", "-q", "origin", "--delete", "tmp-x"], other)
    core_fetch.fetch(git, ctx)                              # without prune: stays
    assert git.ok(["rev-parse", "--verify", "-q", "refs/remotes/origin/tmp-x"], cwd=ctx.bare)
    core_fetch.fetch(git, ctx, prune=True)
    assert not git.ok(["rev-parse", "--verify", "-q", "refs/remotes/origin/tmp-x"], cwd=ctx.bare)


def test_cli_fetch_json_and_table(remote_moved, capsys, monkeypatch):
    from grove.cli.main import main
    git, ctx, _ = remote_moved
    monkeypatch.chdir(ctx.root)
    assert main(["fetch", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert _row(payload["result"]["worktrees"], "main")["behind"] == 1
    assert main(["fetch"]) == 0
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.strip().startswith("main"))
    assert "↓1" in line and "origin/main" in line


def test_mcp_op_fetch(remote_moved):
    from grove.mcp import _ops
    git, ctx, _ = remote_moved
    res = _ops.op_fetch(cwd=str(ctx.root))
    assert _row(res["worktrees"], "main")["behind"] == 1
    assert res["prune"] is False
