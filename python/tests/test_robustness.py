"""0.8.1 — robustness: machine-level git commands don't depend on the cwd, and a
missing base branch gets a helpful suggestion instead of a raw git error."""

import subprocess

import pytest

from grove.core import config, create, gitidentity
from grove.core import setup as core_setup
from grove.core.errors import ValidationError
from grove.core.gitrunner import GitRunner


def _git(args, cwd):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(cwd),
                          check=True, capture_output=True, text=True).stdout.strip()


# --------------------------------------------------------------------------- #
# neutral cwd for `git config --global`
# --------------------------------------------------------------------------- #

@pytest.fixture
def inside_broken_repo(tmp_path, monkeypatch):
    """cwd = a folder whose .git points nowhere (a worktree seen from another
    mount, a deleted repo...). Plain `git config --global` fails here."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / ".git").write_text("gitdir: /does/not/exist/.bare/worktrees/x\n", encoding="utf-8")
    monkeypatch.chdir(broken)
    return broken


def test_global_identity_works_from_a_broken_repo_cwd(inside_broken_repo):
    git = GitRunner()
    res = gitidentity.harden_global(git, name="Tester")
    assert "user.useConfigOnly = true" in res["changes"]
    assert gitidentity._get_global(git, "user.name") == "Tester"
    assert gitidentity.conflicting_url_rewrites(git) == []


def test_ssh_doctor_global_checks_work_from_a_broken_repo_cwd(inside_broken_repo):
    from grove.core import sshdoctor
    findings = sshdoctor._check_global(GitRunner())
    fix = [f for f in findings if f.check == "useconfigonly"]
    assert fix and fix[0].fixer is not None
    fix[0].fixer()                                            # must not raise
    assert gitidentity._get_global(GitRunner(), "user.useConfigOnly") == "true"


# --------------------------------------------------------------------------- #
# missing base branch → suggestion
# --------------------------------------------------------------------------- #

def test_create_with_missing_base_suggests_existing_one(repo):
    git, ctx = repo
    with pytest.raises(ValidationError) as exc:
        create.create_ticket(git, ctx, type="feature", name="x", ticket="PROJ-1",
                             base="production")
    msg = str(exc.value)
    assert "production" in msg and "main" in msg          # names the missing one and a candidate
    assert not (ctx.root / "feature").exists()


def test_create_with_wrong_configured_base_suggests_config_fix(repo):
    git, ctx = repo
    config.DEFAULT_BASE = "production"                   # grove.toml out of date
    with pytest.raises(ValidationError) as exc:
        create.create_ticket(git, ctx, type="feature", name="x", ticket="PROJ-1")
    assert "gwt config set default_base main" in str(exc.value)


def test_create_accepts_an_origin_only_base(repo, origin):
    git, ctx = repo
    # a branch that exists only on origin
    seed = ctx.root.parent / "seed2"
    _git(["clone", "-q", origin, str(seed)], ctx.root.parent)
    _git(["push", "-q", "origin", "HEAD:refs/heads/release-base"], seed)
    _git(["fetch", "-q", "origin"], ctx.bare)
    path = create.create_ticket(git, ctx, type="feature", name="x", ticket="PROJ-1",
                                base="origin/release-base")
    assert path.is_dir()


def test_setup_with_no_usable_base_lists_origin_branches(tmp_path):
    origin = tmp_path / "origin.git"
    _git(["init", "-q", "--bare", str(origin)], tmp_path)   # HEAD -> main (never created)
    seed = tmp_path / "seed"
    _git(["clone", "-q", str(origin), str(seed)], tmp_path)
    (seed / "a.txt").write_text("a\n", encoding="utf-8")
    _git(["checkout", "-q", "-b", "develop"], seed)
    _git(["add", "."], seed)
    _git(["commit", "-qm", "init"], seed)
    _git(["push", "-q", "origin", "develop"], seed)

    with pytest.raises(ValidationError) as exc:
        core_setup.setup(GitRunner(), f"file://{origin}", into=tmp_path / "work",
                         name="repo", base_branch="production")
    msg = str(exc.value)
    assert "develop" in msg and "--base develop" in msg
    assert not (tmp_path / "work" / "repo").exists()        # transactional cleanup
