"""doctor hygiene checks (stale locks, temp objects, identity) and the
`gitdir` field of list. Uses the integration ``repo`` fixture."""

import json
import os
import time

import pytest

from grove.core import create, doctor
from grove.core.model import list_worktrees


def _age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _kinds(issues, kind):
    return [i for i in issues if i.kind == kind]


@pytest.fixture
def no_git_running(monkeypatch):
    monkeypatch.setattr(doctor, "_git_running", lambda: False)


# --------------------------------------------------------------------------- #
# stale locks
# --------------------------------------------------------------------------- #

def test_stale_lock_is_reported_and_fixed(repo, no_git_running):
    git, ctx = repo
    lock = ctx.bare / "objects" / "maintenance.lock"
    lock.write_text("", encoding="utf-8")
    _age(lock, 120)

    issues = doctor.diagnose(git, ctx)
    found = _kinds(issues, "stale-lock")
    assert len(found) == 1
    assert found[0].target == ".bare/objects/maintenance.lock"
    assert found[0].fix is not None

    doctor.apply(issues)
    assert not lock.exists()


def test_worktree_head_lock_is_found(repo, no_git_running):
    git, ctx = repo
    admin = next((ctx.bare / "worktrees").iterdir())
    lock = admin / "HEAD.lock"
    lock.write_text("", encoding="utf-8")
    _age(lock, 120)
    targets = [i.target for i in _kinds(doctor.diagnose(git, ctx), "stale-lock")]
    assert f".bare/worktrees/{admin.name}/HEAD.lock" in targets


def test_recent_lock_is_reported_but_not_fixable(repo, no_git_running):
    git, ctx = repo
    lock = ctx.bare / "HEAD.lock"
    lock.write_text("", encoding="utf-8")        # mtime = now: maybe in use
    issues = doctor.diagnose(git, ctx)
    assert not _kinds(issues, "stale-lock")
    recent = _kinds(issues, "lock")
    assert recent and recent[0].fix is None
    doctor.apply(issues)
    assert lock.exists()                         # never touched


def test_lock_not_stale_while_git_runs_until_old(repo, monkeypatch):
    git, ctx = repo
    monkeypatch.setattr(doctor, "_git_running", lambda: True)
    lock = ctx.bare / "packed-refs.lock"
    lock.write_text("", encoding="utf-8")
    _age(lock, 120)                              # old-ish, but git is running
    assert _kinds(doctor.diagnose(git, ctx), "lock")
    _age(lock, 11 * 60)                          # past the hard threshold
    assert _kinds(doctor.diagnose(git, ctx), "stale-lock")


def test_unknown_process_state_uses_hard_threshold(repo, monkeypatch):
    git, ctx = repo
    monkeypatch.setattr(doctor, "_git_running", lambda: None)
    lock = ctx.bare / "config.lock"
    lock.write_text("", encoding="utf-8")
    _age(lock, 120)
    assert not _kinds(doctor.diagnose(git, ctx), "stale-lock")
    _age(lock, 11 * 60)
    assert _kinds(doctor.diagnose(git, ctx), "stale-lock")


# --------------------------------------------------------------------------- #
# temp objects
# --------------------------------------------------------------------------- #

def test_stale_temp_objects_grouped_and_fixed(repo, no_git_running):
    git, ctx = repo
    objs = ctx.bare / "objects"
    (objs / "ab").mkdir(exist_ok=True)
    files = [objs / "ab" / "tmp_obj_1", objs / "tmp_obj_2",
             objs / "pack" / "tmp_pack_3", objs / "pack" / "tmp_idx_4"]
    (objs / "pack").mkdir(exist_ok=True)
    for f in files:
        f.write_text("x", encoding="utf-8")
        _age(f, 120)

    issues = doctor.diagnose(git, ctx)
    tmp = _kinds(issues, "stale-tmp")
    assert len(tmp) == 1                          # one grouped issue
    assert "4" in tmp[0].message
    doctor.apply(issues)
    assert not any(f.exists() for f in files)


def test_real_objects_are_never_touched(repo, no_git_running):
    git, ctx = repo
    before = sorted(p for p in (ctx.bare / "objects").rglob("*") if p.is_file())
    doctor.apply(doctor.diagnose(git, ctx))
    after = sorted(p for p in (ctx.bare / "objects").rglob("*") if p.is_file())
    assert before == after


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #

def test_missing_identity_is_reported(repo, monkeypatch, tmp_path):
    git, ctx = repo
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)
    gc = tmp_path / "noident.gitconfig"
    gc.write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gc))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    found = _kinds(doctor.diagnose(git, ctx), "identity")
    assert found and found[0].fix is None
    assert found[0].target == "main"


def test_identity_ok_is_silent(repo):
    git, ctx = repo                               # conftest sets GIT_AUTHOR_*
    assert not _kinds(doctor.diagnose(git, ctx), "identity")


def test_clean_repo_has_no_hygiene_issues(repo, no_git_running):
    git, ctx = repo
    kinds = {i.kind for i in doctor.diagnose(git, ctx)}
    assert not kinds & {"stale-lock", "lock", "stale-tmp", "identity"}


# --------------------------------------------------------------------------- #
# list: gitdir
# --------------------------------------------------------------------------- #

def test_list_exposes_internal_gitdir(repo):
    git, ctx = repo
    create.create_ticket(git, ctx, type="feature", name="login", ticket="PROJ-1")
    wts = {w.rel_path: w for w in list_worktrees(git, ctx)}
    wt = wts["feature/PROJ-1-login"]
    # git names the admin dir after the LAST path component
    assert wt.gitdir == ".bare/worktrees/PROJ-1-login"
    assert (ctx.root / wt.gitdir).is_dir()
    assert wts["main"].gitdir == ".bare/worktrees/main"
    bare = next(w for w in wts.values() if w.is_bare)
    assert bare.gitdir is None


def test_list_gitdir_in_mcp_and_cli_json(repo, capsys, monkeypatch):
    from grove.cli.main import main
    from grove.mcp import _ops
    git, ctx = repo
    res = _ops.op_list(cwd=str(ctx.root))
    main_row = next(r for r in res["worktrees"] if r["rel_path"] == "main")
    assert main_row["gitdir"] == ".bare/worktrees/main"

    monkeypatch.chdir(ctx.root)
    assert main(["list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    cli_row = next(r for r in payload["result"] if r["rel_path"] == "main")
    assert cli_row["gitdir"] == main_row["gitdir"]
    assert set(cli_row) == set(main_row)          # CLI and MCP expose the same fields
