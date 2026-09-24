"""0.13.0 — skill feedback: outdated-skill detection (S1), `gwt repos` (S3),
and the skill text gaps found reviewing 0.12.0 (S2, S4–S7)."""

import json
import re
from pathlib import Path

import pytest

import grove
from grove.core import doctor
from grove.core import repos as core_repos
from grove.core import skill as core_skill
from grove.core.errors import ValidationError

REPO_SKILL = Path(__file__).resolve().parents[2] / "skills" / "grove"


def _age(skill_dir, version="0.0.1"):
    """Make an installed copy look like it came from another grove version."""
    p = Path(skill_dir) / "SKILL.md"
    p.write_text(re.sub(r'grove-version: "[^"]+"', f'grove-version: "{version}"',
                        p.read_text(encoding="utf-8")), encoding="utf-8")


def _home():
    return core_skill.target_root("agents")


# --- S1: install manifest + status ---------------------------------------- #

def test_install_writes_a_manifest_and_status_reads_it(tmp_path):
    root = tmp_path / "skills"
    core_skill.install(dest_root=root)
    d = root / "grove"
    manifest = json.loads((d / core_skill.MANIFEST).read_text())
    assert manifest["grove_version"] == grove.__version__
    assert set(manifest["files"]) == set(core_skill.install(dest_root=root, dry_run=True)["files"])
    st = core_skill.status(d)
    assert st == {"path": str(d), "installed_version": grove.__version__,
                  "current_version": grove.__version__, "outdated": False, "edited": False}
    (d / "references" / "configuration.md").write_text("mine\n", encoding="utf-8")
    assert core_skill.status(d)["edited"] is True


def test_status_without_manifest_is_unknown(tmp_path):
    root = tmp_path / "skills"
    core_skill.install(dest_root=root)
    (root / "grove" / core_skill.MANIFEST).unlink()
    assert core_skill.status(root / "grove")["edited"] is None
    core_skill.install(dest_root=root)                         # unchanged, but gains a manifest
    assert (root / "grove" / core_skill.MANIFEST).is_file()


def test_version_of_reads_the_frontmatter(tmp_path):
    assert core_skill.version_of(REPO_SKILL) == grove.__version__
    assert core_skill.version_of(tmp_path) is None


def test_install_error_names_both_versions(tmp_path):
    root = tmp_path / "skills"
    core_skill.install(dest_root=root)
    _age(root / "grove")
    with pytest.raises(ValidationError, match=rf"grove 0\.0\.1, this grove is {re.escape(grove.__version__)}"):
        core_skill.install(dest_root=root)


# --- S1: doctor ------------------------------------------------------------ #

def _skill_issues(git, ctx):
    return [i for i in doctor.diagnose(git, ctx) if i.kind == "skill-outdated"]


def test_doctor_is_quiet_without_or_with_a_current_skill(repo):
    git, ctx = repo
    assert _skill_issues(git, ctx) == []
    core_skill.install(dest_root=_home())
    assert _skill_issues(git, ctx) == []


def test_doctor_refreshes_an_untouched_outdated_copy(repo):
    git, ctx = repo
    root = _home()
    core_skill.install(dest_root=root)
    _age(root / "grove")
    core_skill._write_manifest(root / "grove", core_skill._files())   # as an old grove wrote it
    issues = _skill_issues(git, ctx)
    assert len(issues) == 1 and issues[0].severity == doctor.AUTO
    assert issues[0].target == "~/.agents/skills/grove"
    assert doctor.apply(issues) == 1
    assert core_skill.version_of(root / "grove") == grove.__version__
    assert _skill_issues(git, ctx) == []


@pytest.mark.parametrize("edited", [True, False])
def test_doctor_only_reports_an_edited_or_unknown_copy(repo, edited):
    git, ctx = repo
    root = core_skill.target_root("claude")
    core_skill.install(dest_root=root)
    _age(root / "grove")
    if not edited:
        (root / "grove" / core_skill.MANIFEST).unlink()          # installed by 0.12.0
    issues = _skill_issues(git, ctx)
    assert len(issues) == 1 and issues[0].severity == doctor.MANUAL and issues[0].fix is None
    assert "--claude --force" in issues[0].action
    assert ("was edited" if edited else "no install manifest") in issues[0].message


def test_doctor_reports_an_outdated_project_copy(repo):
    git, ctx = repo
    root = ctx.root / "main" / ".agents" / "skills"
    core_skill.install(dest_root=root)
    _age(root / "grove")
    issues = _skill_issues(git, ctx)
    assert [i.target for i in issues] == ["main/.agents/skills/grove"]
    assert issues[0].severity == doctor.MANUAL and "--project --force" in issues[0].action


# --- S3: gwt repos ----------------------------------------------------------- #

def test_find_repos_is_shallow_and_skips_hidden_and_nested(repo, tmp_path):
    git, ctx = repo
    (tmp_path / ".hidden" / "x" / ".bare").mkdir(parents=True)
    (tmp_path / ".hidden" / "x" / ".bare" / "HEAD").write_text("ref: refs/heads/main\n")
    deep = tmp_path / "a" / "b" / "c" / "d"
    (deep / ".bare").mkdir(parents=True)
    (deep / ".bare" / "HEAD").write_text("ref: refs/heads/main\n")
    found = core_repos.find([tmp_path], depth=3)
    paths = [r["path"] for r in found]
    assert str(ctx.root) in paths
    assert not any(".hidden" in p for p in paths) and str(deep) not in paths
    row = next(r for r in found if r["path"] == str(ctx.root))
    assert row["base"] == "main" and row["origin"] and row["name"] == ctx.root.name
    assert str(deep) in [r["path"] for r in core_repos.find([tmp_path], depth=5)]
    # nothing is reported from inside a managed repo (its worktrees, .bare)
    assert not any(p.startswith(str(ctx.root) + "/") for p in paths)


def test_discover_uses_zones_by_default(repo, monkeypatch):
    git, ctx = repo
    monkeypatch.setattr(core_repos, "zone_roots", lambda: [ctx.root.parent])
    res = core_repos.discover()
    assert res["source"] == "default" and str(ctx.root) in [r["path"] for r in res["repos"]]
    monkeypatch.setattr(core_repos, "zone_roots", lambda: [])
    res = core_repos.discover()
    assert res["repos"] == [] and "ask the user" in res["hint"]


def test_zone_roots_strip_gitdir_globs(tmp_path, monkeypatch):
    from grove.core import sshprov
    zone = tmp_path / "work"
    zone.mkdir()

    class Z:
        def __init__(self, d):
            self.scope_dir = d

    class Inv:
        zones = [Z(str(zone) + "/**"), Z(str(zone) + "/"), Z(str(tmp_path / "gone") + "/")]

    monkeypatch.setattr(sshprov, "read_inventory", lambda p: Inv())
    assert core_repos.zone_roots() == [zone]


def test_cli_repos(repo, capsys):
    from grove.cli.main import main
    git, ctx = repo
    assert main(["repos", str(ctx.root.parent), "--json"]) == 0
    res = json.loads(capsys.readouterr().out)["result"]
    assert str(ctx.root) in [r["path"] for r in res["repos"]]


# --- S2, S4–S7: the skill text --------------------------------------------- #

def _skill():
    return (REPO_SKILL / "SKILL.md").read_text(encoding="utf-8")


def test_description_triggers_in_spanish_too():
    desc = re.search(r"^description: (.*)$", _skill(), re.M).group(1)
    assert "arranca" in desc.lower() or "empecemos" in desc.lower()
    assert "origin" in desc and len(desc) <= 1024


def test_flow_covers_a_moved_base():
    body = _skill()
    assert "diverged" in body and "rebase" in body and "--ff-only" in body


def test_skill_covers_the_review_gaps():
    body = _skill()
    assert "grove_repos" in body                               # S3
    assert all(m in body for m in ("existing", "resumed", "created"))   # S6
    assert "grove_compare" in body                             # S7
    assert "git worktree add" in body and ".bare/config" in body
    assert "grove-version" in body and "grove_config" in body   # S1 check


def test_troubleshooting_covers_the_first_push():
    t = (REPO_SKILL / "references" / "troubleshooting.md").read_text(encoding="utf-8")
    assert "GH013" in t and "non-fast-forward" in t and "--force-with-lease" in t


def test_frontmatter_is_valid_yaml():
    yaml = pytest.importorskip("yaml")          # what agentskills validate parses with
    meta = yaml.safe_load(_skill().split("\n---\n", 1)[0][4:])
    assert meta["name"] == "grove" and meta["metadata"]["grove-version"] == grove.__version__


# --- 0.13.1: repos agrees with config (R1) --------------------------------- #

def test_repos_reports_what_config_reports(repo):
    import subprocess
    from grove.mcp import _ops
    git, ctx = repo
    raw = subprocess.run(["git", "--git-dir", str(ctx.bare), "remote", "get-url", "--push", "origin"],
                         capture_output=True, text=True).stdout.strip()
    # a zone-style rewrite: git uses the alias, remote.origin.url keeps the raw URL
    subprocess.run(["git", "--git-dir", str(ctx.bare), "config",
                    "url.git@work-gh:org/.insteadOf", raw], check=True)
    row = next(r for r in core_repos.find([ctx.root.parent]) if r["path"] == str(ctx.root))
    shown = _ops.op_config_show(cwd=str(ctx.root))
    assert row["origin"] == shown["origin"] == "git@work-gh:org/"
    assert row["profile"] == shown["profile"]


def test_repos_profile_is_the_effective_one(repo):
    git, ctx = repo
    toml = ctx.bare / "grove.toml"
    toml.write_text('default_base = "main"\n', encoding="utf-8")         # no profile key
    assert core_repos._describe(ctx.root)["profile"] == "default"
    toml.write_text('profile = "personal"\ndefault_base = "main"\n', encoding="utf-8")
    assert core_repos._describe(ctx.root)["profile"] == "personal"


# --- 0.13.1: skill review follow-ups (R2, R3) ------------------------------ #

def test_reset_gotcha_points_to_the_flow():
    body = _skill()
    gotcha = body[body.index("**`grove_reset`"):].split("\n- ", 1)[0]
    assert "When origin moved" in gotcha and "--ff-only" not in gotcha


def test_table_covers_publish_and_ssh():
    table = _skill().split("## Pick the operation", 1)[1].split("\n\n", 2)[1]
    assert "grove_publish" in table and "grove_ssh_check" in table and "grove_ssh_add" in table


def test_long_gotchas_moved_to_references():
    t = (REPO_SKILL / "references" / "troubleshooting.md").read_text(encoding="utf-8")
    c = (REPO_SKILL / "references" / "configuration.md").read_text(encoding="utf-8")
    assert "GIT_DIR=" in t and "extensions.relativeWorktrees" in c
    assert "GIT_DIR=<repo>" not in _skill()


# --- 0.13.2: install refreshes an untouched outdated copy ------------------ #

def test_install_refreshes_an_untouched_outdated_copy(tmp_path):
    root = tmp_path / "skills"
    core_skill.install(dest_root=root)
    _age(root / "grove")
    core_skill._write_manifest(root / "grove", core_skill._files())   # as an older grove left it
    res = core_skill.install(dest_root=root)                          # no force needed
    assert res["mode"] == "updated"
    assert core_skill.version_of(root / "grove") == grove.__version__
    assert core_skill.status(root / "grove")["edited"] is False


def test_install_still_refuses_edited_or_unknown_copies(tmp_path):
    root = tmp_path / "skills"
    core_skill.install(dest_root=root)
    _age(root / "grove")                                      # edited after install
    with pytest.raises(ValidationError, match="and it was edited"):
        core_skill.install(dest_root=root)
    (root / "grove" / core_skill.MANIFEST).unlink()           # installed by 0.12.0
    with pytest.raises(ValidationError, match="no install manifest"):
        core_skill.install(dest_root=root)
    assert core_skill.install(dest_root=root, force=True)["mode"] == "updated"
