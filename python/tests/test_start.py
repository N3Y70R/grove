"""0.9.2 — `gwt start` / `grove_start`: one idempotent call to start (or resume)
work on a ticket from a base: fetch, then return the existing worktree, bring
the existing branch, or create it from the freshly fetched base."""

import json
import subprocess

import pytest

from grove.core import create, start
from grove.core.errors import ValidationError
from grove.core.model import list_worktrees


def _git(args, cwd):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def teammate(repo, origin, tmp_path):
    """A second clone that pushes to origin."""
    git, ctx = repo
    other = tmp_path / "teammate"
    _git(["clone", "-q", origin, str(other)], tmp_path)
    return git, ctx, other


def _push_commit(clone, branch="main", name="t.txt"):
    (clone / name).write_text(branch + "\n", encoding="utf-8")
    _git(["add", "."], clone)
    _git(["commit", "-qm", f"work on {branch}"], clone)
    _git(["push", "-q", "origin", f"HEAD:{branch}"], clone)


def _upstream(path):
    r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], cwd=str(path),
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def test_start_creates_from_the_freshly_fetched_base(teammate):
    git, ctx, other = teammate
    _push_commit(other)                                     # origin/main moved on
    res = start.start(git, ctx, type="feature", name="login", ticket="PROJ-1")
    assert res["mode"] == "created"
    assert res["branch"] == "feature/PROJ-1-login"
    assert res["base"] == "origin/main"
    wt = ctx.root / "feature" / "PROJ-1-login"
    assert (wt / "t.txt").exists()                          # includes the teammate's commit
    assert _upstream(wt) is None                            # not tracking origin/main
    assert res["gitdir"] == ".bare/worktrees/PROJ-1-login"
    assert any("push -u" in s for s in res["next_steps"])


def test_start_is_idempotent(teammate):
    git, ctx, _ = teammate
    first = start.start(git, ctx, type="feature", name="login", ticket="PROJ-1")
    again = start.start(git, ctx, type="feature", name="other words", ticket="PROJ-1")
    assert again["mode"] == "existing"
    assert again["path"] == first["path"]


def test_start_resumes_a_branch_that_only_exists_on_origin(teammate):
    git, ctx, other = teammate
    _git(["checkout", "-q", "-b", "feature/PROJ-7-payments"], other)
    _push_commit(other, "feature/PROJ-7-payments")
    res = start.start(git, ctx, type="feature", name="whatever", ticket="PROJ-7")
    assert res["mode"] == "resumed"
    assert res["branch"] == "feature/PROJ-7-payments"
    assert _upstream(ctx.root / "feature" / "PROJ-7-payments") == "origin/feature/PROJ-7-payments"


def test_start_refuses_ambiguous_ticket(teammate):
    git, ctx, other = teammate
    for b in ("feature/PROJ-8-a", "fix/PROJ-8-b"):
        _git(["checkout", "-q", "-b", b], other)
        _push_commit(other, b, name=b.replace("/", "_"))
    with pytest.raises(ValidationError) as exc:
        start.start(git, ctx, type="feature", name="x", ticket="PROJ-8")
    assert "feature/PROJ-8-a" in str(exc.value) and "fix/PROJ-8-b" in str(exc.value)


def test_create_from_remote_base_does_not_track_it(teammate):
    """Regression: `create --base origin/x` made origin/x the new branch's upstream."""
    git, ctx, other = teammate
    _git(["checkout", "-q", "-b", "release-base"], other)
    _push_commit(other, "release-base")
    _git(["fetch", "-q", "origin"], ctx.bare)
    path = create.create_ticket(git, ctx, type="feature", name="x", ticket="PROJ-2",
                                base="origin/release-base")
    assert _upstream(path) is None


def test_start_cli_json_and_mcp(teammate, capsys, monkeypatch):
    from grove.cli.main import main
    from grove.mcp import _ops
    git, ctx, _ = teammate
    monkeypatch.chdir(ctx.root)
    assert main(["start", "PROJ-3", "feature", "cli path", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)["result"]
    assert res["mode"] == "created" and res["branch"] == "feature/PROJ-3-cli-path"
    again = _ops.op_start(type="feature", name="x", ticket="PROJ-3", cwd=str(ctx.root))
    assert again["mode"] == "existing"
