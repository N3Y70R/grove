"""0.11.0 — opt-in relative worktree paths (`relative_worktrees` in grove.toml).

Needs git >= 2.48 for the real thing; those tests are skipped on older git.
The "git too old" paths are tested by faking the version.
"""

import json
import shutil
import subprocess

import pytest

from grove.core import config as cfg
from grove.core import create, doctor
from grove.core import worktree_paths as wp
from grove.core.errors import ValidationError
from grove.core.gitrunner import GitRunner

needs_git_248 = pytest.mark.skipif(wp.git_version(GitRunner()) < wp.MIN_GIT,
                                   reason="relative worktrees need git >= 2.48")


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def _gitfile(path):
    return (path / ".git").read_text().strip()


def _set(ctx, value, capsys, monkeypatch):
    from grove.cli.main import main
    monkeypatch.chdir(ctx.root)
    rc = main(["config", "set", "relative_worktrees", value, "--json"])
    return rc, json.loads(capsys.readouterr().out)


@needs_git_248
def test_enable_converts_existing_and_new_worktrees(repo, capsys, monkeypatch):
    git, ctx = repo
    rc, payload = _set(ctx, "true", capsys, monkeypatch)
    assert rc == 0 and payload["result"]["value"] is True
    assert _git(["config", "--get", "worktree.useRelativePaths"], ctx.bare) == "true"
    assert _gitfile(ctx.root / "main") == "gitdir: ../.bare/worktrees/main"
    path = create.create_ticket(git, ctx, type="feature", name="x", ticket="PROJ-1")
    assert _gitfile(path) == "gitdir: ../../.bare/worktrees/PROJ-1-x"


@needs_git_248
def test_disable_goes_back_to_absolute_and_old_git_compatible(repo, capsys, monkeypatch):
    git, ctx = repo
    _set(ctx, "true", capsys, monkeypatch)
    rc, _ = _set(ctx, "false", capsys, monkeypatch)
    assert rc == 0
    assert _gitfile(ctx.root / "main").startswith("gitdir: /")
    ext = subprocess.run(["git", "config", "--get", "extensions.relativeWorktrees"],
                         cwd=str(ctx.bare), capture_output=True, text=True).stdout.strip()
    assert ext == ""                                   # older git can open it again


@needs_git_248
def test_repo_works_from_another_mount_with_relative_paths(repo, capsys, monkeypatch, tmp_path):
    git, ctx = repo
    _set(ctx, "true", capsys, monkeypatch)
    moved = tmp_path / "other-mount" / "repo"
    moved.parent.mkdir()
    shutil.move(str(ctx.root), str(moved))
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], moved / "main") == "main"


@needs_git_248
def test_doctor_applies_the_setting_when_state_drifted(repo, monkeypatch):
    git, ctx = repo
    monkeypatch.setattr(doctor, "_git_running", lambda: False)
    cfg.set_repo_value(ctx.bare, "relative_worktrees", "true")   # written, not applied
    cfg.load(ctx.bare)
    issues = doctor.diagnose(git, ctx)
    fix = [i for i in issues if i.kind == "worktree-paths"]
    assert fix and fix[0].fix is not None
    doctor.apply(issues)
    assert _gitfile(ctx.root / "main").startswith("gitdir: ../")
    assert not [i for i in doctor.diagnose(git, ctx) if i.kind == "worktree-paths"]


def test_enable_refused_on_old_git_and_config_untouched(repo, monkeypatch, capsys):
    git, ctx = repo
    monkeypatch.setattr(wp, "git_version", lambda g: (2, 34, 1))
    with pytest.raises(ValidationError) as exc:
        wp.set_relative(git, ctx, True)
    assert "2.48" in str(exc.value)
    assert cfg.read_repo_config(ctx.bare).get("relative_worktrees") in (None, False)


def test_doctor_reports_manual_when_git_is_too_old(repo, monkeypatch):
    git, ctx = repo
    monkeypatch.setattr(doctor, "_git_running", lambda: False)
    monkeypatch.setattr(wp, "git_version", lambda g: (2, 34, 1))
    cfg.set_repo_value(ctx.bare, "relative_worktrees", "true")
    cfg.load(ctx.bare)
    issue = next(i for i in doctor.diagnose(git, ctx) if i.kind == "worktree-paths")
    assert issue.fix is None and "2.48" in issue.message


@pytest.mark.parametrize("raw,expected", [("true", True), ("yes", True), ("1", True),
                                          ("false", False), ("no", False), ("0", False)])
def test_bool_values(tmp_path, raw, expected):
    bare = tmp_path / ".bare"
    bare.mkdir()
    assert cfg.set_repo_value(bare, "relative_worktrees", raw)["relative_worktrees"] is expected


def test_bool_value_rejects_garbage(tmp_path):
    bare = tmp_path / ".bare"
    bare.mkdir()
    with pytest.raises(ValidationError):
        cfg.set_repo_value(bare, "relative_worktrees", "maybe")


def test_git_version_parses_apple_git(monkeypatch):
    class G:
        def run(self, *a, **k):
            import subprocess as sp
            return sp.CompletedProcess(a, 0, "git version 2.54.0 (Apple Git-157)\n", "")
    assert wp.git_version(G()) == (2, 54, 0)


@needs_git_248
def test_setup_with_a_relative_profile(origin, tmp_path, monkeypatch, capsys):
    """A profile with relative_worktrees = true yields relative worktrees at setup."""
    from grove.cli.main import main
    gconf = tmp_path / "grove-config.toml"
    gconf.write_text('[profiles.rel]\ndefault_base = "main"\nrelative_worktrees = true\n',
                     encoding="utf-8")
    monkeypatch.setattr(cfg, "GLOBAL_CONFIG", gconf)
    assert main(["setup", origin, "--into", str(tmp_path), "--name", "r",
                 "--profile", "rel", "--json"]) == 0
    assert _gitfile(tmp_path / "r" / "main") == "gitdir: ../.bare/worktrees/main"


def test_setup_with_a_relative_profile_on_old_git_warns_and_succeeds(origin, tmp_path, monkeypatch, capsys):
    from grove.cli.main import main
    monkeypatch.setattr(wp, "git_version", lambda g: (2, 34, 1))
    gconf = tmp_path / "grove-config.toml"
    gconf.write_text('[profiles.rel]\ndefault_base = "main"\nrelative_worktrees = true\n',
                     encoding="utf-8")
    monkeypatch.setattr(cfg, "GLOBAL_CONFIG", gconf)
    assert main(["setup", origin, "--into", str(tmp_path), "--name", "r",
                 "--profile", "rel", "--json"]) == 0
    log = " ".join(json.loads(capsys.readouterr().out)["log"])
    assert "2.48" in log
    assert (tmp_path / "r" / "main").is_dir()
