"""0.10.0 — no parking branch: the bare HEAD points at the base, so no internal
branch (`worktree-config-root`) sits among the user's branches. doctor migrates
existing repos."""

import subprocess

import pytest

from grove.core import config as cfg
from grove.core import convert as core_convert
from grove.core import doctor
from grove.core.gitrunner import GitRunner


def _git(args, cwd):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


def _head(bare):
    return _git(["symbolic-ref", "HEAD"], bare)


def _heads(bare):
    return _git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], bare).split()


@pytest.fixture
def quiet_locks(monkeypatch):
    monkeypatch.setattr(doctor, "_git_running", lambda: False)


def test_setup_points_bare_head_at_base_without_parking(repo):
    git, ctx = repo
    assert _head(ctx.bare) == "refs/heads/main"
    assert "worktree-config-root" not in _heads(ctx.bare)
    assert (ctx.root / "main").is_dir()
    assert _git(["log", "--oneline", "-1"], ctx.root)      # plain git log works at the root


def test_new_grove_toml_has_no_parking_key(tmp_path):
    bare = tmp_path / ".bare"
    bare.mkdir()
    cfg.apply_policy(cfg.resolve_profile("default"))
    cfg.write_repo_config(bare, cfg.effective_policy())
    assert "parking_branch" not in (bare / "grove.toml").read_text()


@pytest.mark.parametrize("into", [False, True])
def test_convert_points_bare_head_at_base(origin, tmp_path, into):
    clone = tmp_path / "clone"
    _git(["clone", "-q", origin, str(clone)], tmp_path)
    _git(["checkout", "-q", "-B", "main", "origin/main"], clone)
    dest = tmp_path / "converted" if into else None
    ctx = core_convert.convert(GitRunner(), path=clone, into=dest, fetch=False)
    assert _head(ctx.bare) == "refs/heads/main"
    assert "worktree-config-root" not in _heads(ctx.bare)


def _make_legacy(ctx):
    """What setup did before 0.10.0."""
    _git(["branch", "worktree-config-root", "main"], ctx.bare)
    _git(["symbolic-ref", "HEAD", "refs/heads/worktree-config-root"], ctx.bare)


def test_doctor_migrates_a_legacy_parking_branch(repo, quiet_locks):
    git, ctx = repo
    _make_legacy(ctx)
    issues = doctor.diagnose(git, ctx)
    kinds = {i.kind: i for i in issues}
    assert kinds["bare-head"].fix and kinds["parking-branch"].fix
    doctor.apply(issues)
    assert _head(ctx.bare) == "refs/heads/main"
    assert "worktree-config-root" not in _heads(ctx.bare)
    assert not {"bare-head", "parking-branch"} & {i.kind for i in doctor.diagnose(git, ctx)}


def test_doctor_keeps_a_parking_branch_with_its_own_commits(repo, quiet_locks):
    git, ctx = repo
    _make_legacy(ctx)
    tree = _git(["rev-parse", "main^{tree}"], ctx.bare)
    extra = _git(["commit-tree", tree, "-p", "worktree-config-root", "-m", "stray"], ctx.bare)
    _git(["update-ref", "refs/heads/worktree-config-root", extra], ctx.bare)
    issues = doctor.diagnose(git, ctx)
    park = next(i for i in issues if i.kind == "parking-branch")
    assert park.fix is None                                   # manual: never deletes work
    doctor.apply(issues)
    assert _head(ctx.bare) == "refs/heads/main"               # HEAD still fixed
    assert "worktree-config-root" in _heads(ctx.bare)


def test_doctor_repoints_a_dangling_bare_head(repo, quiet_locks):
    git, ctx = repo
    _git(["symbolic-ref", "HEAD", "refs/heads/gone"], ctx.bare)
    issues = doctor.diagnose(git, ctx)
    assert any(i.kind == "bare-head" and i.fix for i in issues)
    doctor.apply(issues)
    assert _head(ctx.bare) == "refs/heads/main"
