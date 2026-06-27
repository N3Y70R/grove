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


def test_setup_writes_git_pointer_by_default(repo):
    _, ctx = repo
    p = ctx.root / ".git"
    assert p.is_file()
    assert p.read_text(encoding="utf-8").strip() == "gitdir: ./.bare"


def test_setup_no_git_pointer_flag(tmp_path, origin):
    from grove.core import config as cfg, setup as core_setup
    from grove.core.gitrunner import GitRunner
    cfg.apply_policy(cfg.resolve_profile("default"))
    ctx = core_setup.setup(GitRunner(), origin, into=tmp_path / "w", name="r",
                           base_branch=cfg.DEFAULT_BASE, git_pointer=False)
    assert not (ctx.root / ".git").exists()


def test_setup_rolls_back_partial_on_failure(tmp_path, origin, monkeypatch):
    from grove.core import config as cfg, setup as core_setup
    from grove.core.gitrunner import GitRunner
    cfg.apply_policy(cfg.resolve_profile("default"))

    def boom(_root):
        raise RuntimeError("boom late in setup")

    monkeypatch.setattr(core_setup, "write_git_pointer", boom)
    into = tmp_path / "w"
    with pytest.raises(RuntimeError):
        core_setup.setup(GitRunner(), origin, into=into, name="r",
                         base_branch=cfg.DEFAULT_BASE)
    assert not (into / "r").exists()        # partial folder cleaned up → retry is clean


def test_setup_keep_on_error_leaves_partial(tmp_path, origin, monkeypatch):
    from grove.core import config as cfg, setup as core_setup
    from grove.core.gitrunner import GitRunner
    cfg.apply_policy(cfg.resolve_profile("default"))

    def boom(_root):
        raise RuntimeError("boom late in setup")

    monkeypatch.setattr(core_setup, "write_git_pointer", boom)
    into = tmp_path / "w"
    with pytest.raises(RuntimeError):
        core_setup.setup(GitRunner(), origin, into=into, name="r",
                         base_branch=cfg.DEFAULT_BASE, keep_on_error=True)
    assert (into / "r" / ".bare").exists()  # preserved for debugging


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


# --- create temp --base ------------------------------------------------- #

def test_create_temp_from_specific_base(repo):
    git, ctx = repo
    # A feature branch with an extra commit beyond main.
    work = create.create_ticket(git, ctx, type="feature", name="src")
    (work / "app.txt").write_text("changed\n", encoding="utf-8")
    git.run(["add", "."], cwd=work)
    git.run(["-c", "commit.gpgsign=false", "commit", "-m", "wip"], cwd=work)
    feat_head = git.out(["rev-parse", "feature/src"], cwd=ctx.bare)

    # temp worktree branched off that feature branch (not main).
    tmp = create.create_temp(git, ctx, name="spike", base="feature/src")
    assert tmp == ctx.root / "temp" / "spike"
    tmp_head = git.out(["rev-parse", "temp/spike"], cwd=ctx.bare)
    assert tmp_head == feat_head  # started from the requested base, not main


# --- setup: auto-detect base from origin's default --------------------- #

def test_setup_autodetects_base_when_profile_base_missing(tmp_path):
    import subprocess
    from grove.core import config as cfg, setup as core_setup
    from grove.core.gitrunner import GitRunner

    def g(args, cwd):
        subprocess.run(["git", "-c", "commit.gpgsign=false", *args],
                       cwd=str(cwd), check=True, capture_output=True, text=True)

    # Origin whose default branch is 'production' (there is no 'main').
    bare = tmp_path / "origin.git"
    g(["init", "-q", "--bare", str(bare)], tmp_path)
    seed = tmp_path / "seed"
    g(["clone", "-q", str(bare), str(seed)], tmp_path)
    (seed / "f.txt").write_text("x\n", encoding="utf-8")
    g(["checkout", "-q", "-b", "production"], seed)
    g(["add", "."], seed)
    g(["commit", "-qm", "init"], seed)
    g(["push", "-q", "origin", "production"], seed)
    g(["symbolic-ref", "HEAD", "refs/heads/production"], bare)  # origin default

    cfg.apply_policy(cfg.resolve_profile("default"))  # default base = 'main'
    git = GitRunner()
    ctx = core_setup.setup(git, f"file://{bare}", into=tmp_path / "work",
                           name="repo", base_branch=cfg.DEFAULT_BASE)  # asks 'main'
    assert ctx.base == "production"             # fell back to origin's default
    assert (ctx.root / "production").is_dir()


# --- publish: create integration branch from base --------------------- #

def test_ensure_integration_creates_from_base(repo):
    from grove.core import publish as core_publish
    git, ctx = repo

    # Branch doesn't exist anywhere yet → created from 'main'.
    path, created = core_publish.ensure_integration(
        git, ctx, "temporary-unified-test", create_base="main"
    )
    assert created is True
    assert path == ctx.root / "temporary-unified-test"
    assert path.is_dir()

    # Idempotent: now it exists as a worktree → found, not created.
    path2, created2 = core_publish.ensure_integration(
        git, ctx, "temporary-unified-test", create_base="main"
    )
    assert created2 is False
    assert path2 == path


def test_doctor_detects_and_fixes_missing_git_pointer(repo):
    from grove.core import doctor as core_doctor
    git, ctx = repo
    (ctx.root / ".git").unlink()                    # remove the pointer
    issues = core_doctor.diagnose(git, ctx)
    ptr = [i for i in issues if i.kind == "git-pointer"]
    assert ptr and ptr[0].fix is not None
    core_doctor.apply(issues)
    assert (ctx.root / ".git").is_file()
    assert (ctx.root / ".git").read_text().strip() == "gitdir: ./.bare"


def test_ensure_integration_missing_without_base_errors(repo):
    from grove.core import publish as core_publish
    from grove.core.errors import ValidationError
    git, ctx = repo
    with pytest.raises(ValidationError):
        core_publish.ensure_integration(git, ctx, "temporary-unified-test")
