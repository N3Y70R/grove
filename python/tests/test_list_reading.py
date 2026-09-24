"""0.7.2 — reading `list`: ahead/behind vs the base when there is no upstream,
`kind: "base"`, and correct paths when the repo is seen from another mount."""

import json
import shutil
import subprocess

import pytest

from grove.core import create, doctor
from grove.core.errors import ValidationError
from grove.core.model import list_worktrees
from grove.core.repo import RepoContext


def _git(args, cwd):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


def _commit(path, n=1):
    for i in range(n):
        (path / f"f{i}.txt").write_text(f"{i}\n", encoding="utf-8")
        _git(["add", "."], path)
        _git(["commit", "-qm", f"c{i}"], path)


def _rows(git, ctx):
    return {w.rel_path: w for w in list_worktrees(git, ctx)}


# --------------------------------------------------------------------------- #
# ahead/behind vs base without upstream
# --------------------------------------------------------------------------- #

def test_new_branch_without_upstream_is_measured_against_base(repo):
    git, ctx = repo
    path = create.create_ticket(git, ctx, type="feature", name="login", ticket="PROJ-1")
    _commit(path, 3)
    wt = _rows(git, ctx)["feature/PROJ-1-login"]
    assert wt.upstream is None
    assert (wt.ahead, wt.behind) == (3, 0)
    assert wt.compared_to == "main"


def test_branch_with_upstream_keeps_upstream_comparison(repo):
    git, ctx = repo
    wt = _rows(git, ctx)["main"]
    assert wt.upstream == "origin/main"
    assert wt.compared_to == "origin/main"


def test_list_json_and_table_show_the_reference(repo, capsys, monkeypatch):
    from grove.cli.main import main
    git, ctx = repo
    path = create.create_ticket(git, ctx, type="feature", name="login", ticket="PROJ-1")
    _commit(path, 2)
    monkeypatch.chdir(ctx.root)
    main(["list", "--json"])
    row = next(r for r in json.loads(capsys.readouterr().out)["result"]
               if r["rel_path"] == "feature/PROJ-1-login")
    assert row["ahead"] == 2 and row["compared_to"] == "main"
    main(["list"])
    line = next(l for l in capsys.readouterr().out.splitlines()
                if l.startswith("feature/PROJ-1-login"))
    assert "↑2" in line and "vs main" in line and "no upstream" in line


def test_reset_losses_do_not_claim_unpushed_commits_vs_base(repo):
    """Without upstream, ahead counts commits vs the BASE; the reset warning must
    not present them as 'not pushed' commits of an upstream."""
    from grove.mcp import _ops
    git, ctx = repo
    path = create.create_ticket(git, ctx, type="feature", name="login", ticket="PROJ-1")
    _commit(path, 2)
    wt = _rows(git, ctx)["feature/PROJ-1-login"]
    assert _ops._reset_losses(wt) == ["2 commit(s) ahead of main with no upstream (may not be pushed)"]


# --------------------------------------------------------------------------- #
# kind: base (and protected)
# --------------------------------------------------------------------------- #

def test_base_worktree_has_kind_base(repo):
    git, ctx = repo
    assert _rows(git, ctx)["main"].classification.kind == "base"


def test_base_worktree_is_protected_from_remove(repo):
    from grove.core import remove as core_remove
    git, ctx = repo
    wt = core_remove.resolve_target(git, ctx, "main")
    with pytest.raises(ValidationError):
        core_remove.remove_one(git, ctx, wt)
    assert (ctx.root / "main").is_dir()


# --------------------------------------------------------------------------- #
# repo seen from another mount
# --------------------------------------------------------------------------- #

@pytest.fixture
def moved(repo, tmp_path):
    """The same repo seen at another path (like a container/VM mount): git's
    records still point at the original location."""
    git, ctx = repo
    create.create_ticket(git, ctx, type="feature", name="login", ticket="PROJ-1")
    other = tmp_path / "mount" / "repo"
    other.parent.mkdir()
    shutil.move(str(ctx.root), str(other))
    return git, RepoContext(root=other, bare=other / ".bare", name="repo", base="main")


def test_rel_path_and_exists_from_another_mount(moved):
    git, ctx = moved
    rows = _rows(git, ctx)
    assert {"main", "feature/PROJ-1-login"} <= set(rows)
    wt = rows["feature/PROJ-1-login"]
    assert wt.exists and not wt.prunable
    assert wt.path == ctx.root / "feature" / "PROJ-1-login"
    assert wt.gitdir == ".bare/worktrees/PROJ-1-login"


def test_doctor_does_not_prune_worktrees_seen_from_another_mount(moved, monkeypatch):
    git, ctx = moved
    monkeypatch.setattr(doctor, "_git_running", lambda: False)
    issues = doctor.diagnose(git, ctx)
    assert not [i for i in issues if i.kind == "orphan"]
    doctor.apply(issues)
    assert (ctx.bare / "worktrees" / "PROJ-1-login").is_dir()   # registration kept
