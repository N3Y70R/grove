"""Integration tests for `convert` (existing clone → grove model)."""

import subprocess

import pytest

from grove.core import convert as core_convert
from grove.core.errors import UsageError, ValidationError
from grove.core.gitrunner import GitRunner


def _g(args, cwd):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args],
                   cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def clone(tmp_path):
    """A normal (non-grove) clone of an origin with branch 'main'. Returns its path."""
    origin = tmp_path / "origin.git"
    _g(["init", "-q", "--bare", str(origin)], tmp_path)
    seed = tmp_path / "seed"
    _g(["clone", "-q", str(origin), str(seed)], tmp_path)
    (seed / "app.txt").write_text("base\n", encoding="utf-8")
    _g(["checkout", "-q", "-b", "main"], seed)
    _g(["add", "."], seed)
    _g(["commit", "-qm", "init"], seed)
    _g(["push", "-q", "origin", "main"], seed)
    # Point the bare origin's HEAD at 'main' so clones check it out regardless of
    # the host git's init.defaultBranch (CI runners often default to 'master').
    _g(["symbolic-ref", "HEAD", "refs/heads/main"], origin)

    work = tmp_path / "work"
    _g(["clone", "-q", str(origin), str(work)], tmp_path)  # normal clone, on main
    _g(["checkout", "-q", "-B", "main", "origin/main"], work)  # be explicit about the branch
    return work


def test_convert_in_place_basic(clone):
    ctx = core_convert.convert(GitRunner(), path=clone)
    assert ctx.root == clone
    assert (clone / ".bare").is_dir()
    assert (clone / "main").is_dir()
    assert (clone / ".git").is_file()                      # root pointer
    assert (clone / ".git").read_text().strip() == "gitdir: ./.bare"
    # history is intact
    out = subprocess.run(["git", "-C", str(clone / ".bare"), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "init" in out


def test_convert_preserves_ignored_and_wip(clone):
    (clone / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _g(["add", ".gitignore"], clone)
    _g(["commit", "-qm", "add gitignore"], clone)
    (clone / "secret.txt").write_text("KEEPME\n", encoding="utf-8")   # ignored
    (clone / "new.txt").write_text("untracked\n", encoding="utf-8")   # untracked
    (clone / "app.txt").write_text("modified\n", encoding="utf-8")    # tracked, dirty

    core_convert.convert(GitRunner(), path=clone)

    wt = clone / "main"
    assert (wt / "secret.txt").read_text() == "KEEPME\n"   # ignored preserved (moved)
    assert (wt / "new.txt").exists()                       # untracked restored via stash
    assert (wt / "app.txt").read_text() == "modified\n"    # uncommitted change restored


def test_convert_into_leaves_source_untouched(clone, tmp_path):
    dest = tmp_path / "converted"
    ctx = core_convert.convert(GitRunner(), path=clone, into=dest)
    assert ctx.root == dest
    assert (dest / ".bare").is_dir()
    assert (dest / "main").is_dir()
    # source still a normal clone
    assert (clone / ".git").is_dir()
    assert not (clone / ".bare").exists()


def test_convert_blocks_submodules(clone):
    (clone / ".gitmodules").write_text("[submodule \"x\"]\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        core_convert.convert(GitRunner(), path=clone)


def test_convert_dry_run_makes_no_changes(clone):
    ctx = core_convert.convert(GitRunner(), path=clone, dry_run=True)
    assert ctx.base == "main"
    assert not (clone / ".bare").exists()      # nothing happened
    assert (clone / ".git").is_dir()           # still a normal clone


def test_convert_rejects_non_repo(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    with pytest.raises(UsageError):
        core_convert.convert(GitRunner(), path=d)


def test_convert_into_rolls_back_on_failure(clone, tmp_path, monkeypatch):
    dest = tmp_path / "converted"

    def boom(*a, **k):
        raise RuntimeError("boom mid-convert")

    monkeypatch.setattr(core_convert, "_make_worktrees", boom)
    with pytest.raises(RuntimeError):
        core_convert.convert(GitRunner(), path=clone, into=dest)
    assert not dest.exists()                      # partial target cleaned up
    assert (clone / ".git").is_dir()              # source untouched


def test_convert_into_keep_on_error_leaves_partial(clone, tmp_path, monkeypatch):
    dest = tmp_path / "converted"

    def boom(*a, **k):
        raise RuntimeError("boom mid-convert")

    monkeypatch.setattr(core_convert, "_make_worktrees", boom)
    with pytest.raises(RuntimeError):
        core_convert.convert(GitRunner(), path=clone, into=dest, keep_on_error=True)
    assert (dest / ".bare").exists()              # partial state preserved for debugging


def test_convert_relocates_ignored_nested_in_tracked_dirs(clone):
    """A tracked dir that also holds ignored files (e.g. pkg/.venv) must not be
    left behind at the root: ignored content moves into the worktree and the
    tracked duplicates are dropped (regression: the whole dir was skipped)."""
    (clone / ".gitignore").write_text(".venv/\n__pycache__/\n", encoding="utf-8")
    (clone / "pkg").mkdir()
    (clone / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _g(["add", "."], clone)
    _g(["commit", "-qm", "add pkg"], clone)
    (clone / "pkg" / ".venv" / "bin").mkdir(parents=True)
    (clone / "pkg" / ".venv" / "bin" / "python").write_text("venv\n", encoding="utf-8")
    (clone / "pkg" / "__pycache__").mkdir()
    (clone / "pkg" / "__pycache__" / "mod.pyc").write_text("pyc\n", encoding="utf-8")

    core_convert.convert(GitRunner(), path=clone)

    leftovers = {p.name for p in clone.iterdir()} - {".bare", ".git", "main", "artifacts"}
    assert leftovers == set()                                  # nothing orphaned at root
    wt = clone / "main"
    assert (wt / "pkg" / "mod.py").read_text() == "x = 1\n"    # tracked, from git
    assert (wt / "pkg" / ".venv" / "bin" / "python").read_text() == "venv\n"
    assert (wt / "pkg" / "__pycache__" / "mod.pyc").read_text() == "pyc\n"


def test_convert_keeps_conflicting_ignored_file_and_reports(clone, monkeypatch):
    """If an ignored file already exists in the worktree with other content, it is
    kept at the root (never overwritten or deleted) and reported."""
    (clone / ".gitignore").write_text("local.cfg\n", encoding="utf-8")
    _g(["add", "."], clone)
    _g(["commit", "-qm", "ignore local.cfg"], clone)
    (clone / "local.cfg").write_text("mine\n", encoding="utf-8")
    steps = []

    real_make = core_convert._make_worktrees

    def make_and_plant(git, bare, root, wts, origin_url, step):
        real_make(git, bare, root, wts, origin_url, step)
        (root / "main" / "local.cfg").write_text("theirs\n", encoding="utf-8")

    monkeypatch.setattr(core_convert, "_make_worktrees", make_and_plant)
    core_convert.convert(GitRunner(), path=clone, step=steps.append)

    assert (clone / "local.cfg").read_text() == "mine\n"         # kept, not lost
    assert (clone / "main" / "local.cfg").read_text() == "theirs\n"
    assert any("local.cfg" in s for s in steps)                 # and reported


def test_convert_writes_repo_config_with_detected_base(clone):
    ctx = core_convert.convert(GitRunner(), path=clone)
    cfg_file = ctx.bare / "grove.toml"
    assert cfg_file.is_file()
    text = cfg_file.read_text()
    assert 'default_base = "main"' in text


def test_convert_applies_profile(clone):
    ctx = core_convert.convert(GitRunner(), path=clone, profile="personal")
    text = (ctx.bare / "grove.toml").read_text()
    assert 'allowed_types = ["feature", "fix"]' in text


def test_convert_rejects_unknown_profile(clone):
    with pytest.raises(UsageError):
        core_convert.convert(GitRunner(), path=clone, profile="nope")
    assert (clone / ".git").is_dir()                            # untouched


def test_convert_into_writes_repo_config(clone, tmp_path):
    dest = tmp_path / "converted"
    ctx = core_convert.convert(GitRunner(), path=clone, into=dest)
    assert (ctx.bare / "grove.toml").is_file()


def test_convert_cli_profile_json(clone, capsys):
    import json

    from grove.cli.main import main
    rc = main(["convert", str(clone), "--profile", "personal", "--no-fetch", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["profile"] == "personal"
    assert payload["result"]["base"] == "main"
    assert (clone / ".bare" / "grove.toml").is_file()


def test_convert_mcp_op_profile(clone):
    from grove.mcp import _ops
    res = _ops.op_convert(path=str(clone), profile="personal", fetch=False)
    assert res["profile"] == "personal"
    assert 'allowed_types = ["feature", "fix"]' in (clone / ".bare" / "grove.toml").read_text()
