"""Integration tests: real operations against a throwaway local git origin.

These use the ``repo`` fixture (a grove repo created with the 'default'
profile: base 'main', tickets optional, allowed types feature/fix/hotfix).
"""

from pathlib import Path

import pytest

from grove.core import compare, create, patch, track
from grove.core.errors import ValidationError
from grove.core.model import list_worktrees


def _rel_paths(git, ctx):
    return {w.rel_path for w in list_worktrees(git, ctx, with_status=False) if not w.is_bare}


def _find(git, ctx, rel):
    for w in list_worktrees(git, ctx, with_status=False):
        if w.rel_path == rel:
            return w
    raise AssertionError(f"worktree {rel!r} not found")


# --- setup -------------------------------------------------------------- #

def test_setup_creates_structure(repo):
    git, ctx = repo
    assert ctx.bare.is_dir()
    assert (ctx.root / "main").is_dir()
    assert (ctx.root / "artifacts").is_dir()


# --- create ------------------------------------------------------------- #

def test_create_ticket_with_key(repo):
    git, ctx = repo
    path = create.create_ticket(git, ctx, type="feature", name="Login Bug", ticket="PROJ-12")
    assert path == ctx.root / "feature" / "PROJ-12-login-bug"
    assert path.is_dir()


def test_create_ticket_optional_without_key(repo):
    git, ctx = repo
    path = create.create_ticket(git, ctx, type="feature", name="cleanup")
    assert path == ctx.root / "feature" / "cleanup"
    assert path.is_dir()


def test_create_rejects_type_not_allowed(repo):
    git, ctx = repo
    with pytest.raises(ValidationError):
        create.create_ticket(git, ctx, type="chore", name="x")


def test_create_duplicate_fails(repo):
    git, ctx = repo
    create.create_ticket(git, ctx, type="feature", name="dup")
    with pytest.raises(ValidationError):
        create.create_ticket(git, ctx, type="feature", name="dup")


def test_list_includes_created_worktrees(repo):
    git, ctx = repo
    create.create_ticket(git, ctx, type="feature", name="thing")
    rels = _rel_paths(git, ctx)
    assert "main" in rels
    assert "feature/thing" in rels


# --- track -------------------------------------------------------------- #

def test_track_local_branch(repo):
    git, ctx = repo
    git.run(["branch", "fix/local-thing", "main"], cwd=ctx.bare)
    path = track.track(git, ctx, branch="fix/local-thing")
    assert path == ctx.root / "fix" / "local-thing"
    assert path.is_dir()


def test_track_unknown_type_warns_but_brings(repo):
    git, ctx = repo
    git.run(["branch", "chore/cleanup", "main"], cwd=ctx.bare)
    warnings = []
    path = track.track(git, ctx, branch="chore/cleanup", warn=warnings.append)
    assert path.is_dir()
    assert warnings, "expected a warning for a type outside allowed_types"


# --- compare ------------------------------------------------------------ #

def test_compare_new_branch_in_sync(repo):
    git, ctx = repo
    create.create_ticket(git, ctx, type="feature", name="cmp")
    res = compare.compare_one(git, ctx, "feature/cmp", "main")
    assert res["status"] == "in sync"
    assert res["ahead"] == 0 and res["behind"] == 0


# --- patch -------------------------------------------------------------- #

def test_patch_wip_is_nonempty(repo, tmp_path):
    git, ctx = repo
    work = create.create_ticket(git, ctx, type="feature", name="patchwip")
    (work / "app.txt").write_text("changed\n", encoding="utf-8")
    wt = _find(git, ctx, "feature/patchwip")
    res = patch.generate(git, ctx, wt, base="main", wip=True, patches_dir=tmp_path)
    assert res["empty"] is False
    assert Path(res["path"]).is_file()


def test_patch_diff_is_empty_for_fresh_branch(repo, tmp_path):
    git, ctx = repo
    create.create_ticket(git, ctx, type="feature", name="patchdiff")
    wt = _find(git, ctx, "feature/patchdiff")
    res = patch.generate(git, ctx, wt, base="main", patches_dir=tmp_path)
    assert res["empty"] is True
