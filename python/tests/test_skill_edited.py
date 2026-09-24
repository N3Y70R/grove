"""0.15.0 — `skill install --dry-run` reports an edited copy instead of failing
(FEEDBACK §23, U1) and `doctor` reports edited copies and which ones it
checked (U2)."""

import json

from grove.core import doctor
from grove.core import skill as core_skill


def _edit(skill_dir):
    p = skill_dir / "SKILL.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n<!-- mine -->\n", encoding="utf-8")


# --- U1 ---------------------------------------------------------------------- #

def test_dry_run_reports_an_edited_copy_instead_of_failing(tmp_path):
    root = tmp_path / "skills"
    core_skill.install(dest_root=root)
    _edit(root / "grove")
    res = core_skill.install(dest_root=root, dry_run=True)
    assert res["mode"] == "edited" and res["dry_run"] is True and res["differs"] == ["SKILL.md"]
    assert "<!-- mine -->" in (root / "grove" / "SKILL.md").read_text()      # untouched


def test_dry_run_reports_an_unverified_copy(tmp_path):
    root = tmp_path / "skills"
    core_skill.install(dest_root=root)
    _edit(root / "grove")
    (root / "grove" / core_skill.MANIFEST).unlink()
    assert core_skill.install(dest_root=root, dry_run=True)["mode"] == "unverified"


def test_differs_is_empty_when_nothing_differs(tmp_path):
    root = tmp_path / "skills"
    assert core_skill.install(dest_root=root)["differs"] == []
    assert core_skill.install(dest_root=root, dry_run=True)["differs"] == []


def test_cli_dry_run_warns_instead_of_failing(tmp_path, capsys):
    from grove.cli.main import main
    root = tmp_path / "s"
    core_skill.install(dest_root=root)
    _edit(root / "grove")
    assert main(["skill", "install", "--path", str(root), "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["mode"] == "edited"


# --- U2 ---------------------------------------------------------------------- #

def _kinds(git, ctx):
    return [(i.kind, i.severity, i.target) for i in doctor.diagnose(git, ctx)
            if i.kind.startswith("skill-")]


def test_doctor_reports_an_edited_current_copy_and_forgets_it_once_restored(repo):
    """The review's experiment: edit a current copy, run doctor, restore."""
    git, ctx = repo
    root = core_skill.target_root("agents")
    core_skill.install(dest_root=root)
    original = (root / "grove" / "SKILL.md").read_bytes()
    _edit(root / "grove")
    assert _kinds(git, ctx) == [("skill-edited", doctor.MANUAL, "~/.agents/skills/grove")]
    (root / "grove" / "SKILL.md").write_bytes(original)
    assert _kinds(git, ctx) == []


def test_skill_edited_names_the_right_flag(repo):
    git, ctx = repo
    root = core_skill.target_root("claude")
    core_skill.install(dest_root=root)
    _edit(root / "grove")
    issue = next(i for i in doctor.diagnose(git, ctx) if i.kind == "skill-edited")
    assert "--claude --force" in issue.action and issue.fix is None


def test_doctor_report_lists_every_copy_it_checked(repo):
    from grove.mcp import _ops
    git, ctx = repo
    assert doctor.skill_report(git, ctx) == []
    core_skill.install(dest_root=core_skill.target_root("agents"))
    core_skill.install(dest_root=core_skill.target_root("claude"))
    core_skill.install(dest_root=ctx.root / "main" / ".agents" / "skills")
    rows = _ops.op_doctor(cwd=str(ctx.root))["skills"]
    assert [(r["scope"], r["path"]) for r in rows] == [
        ("agents", "~/.agents/skills/grove"), ("claude", "~/.claude/skills/grove"),
        ("project", "main/.agents/skills/grove")]
    assert all(r["outdated"] is False and r["edited"] is False for r in rows)


def test_cli_doctor_says_which_copies_it_checked(repo, capsys):
    from grove.cli.main import main
    git, ctx = repo
    core_skill.install(dest_root=core_skill.target_root("claude"))
    capsys.readouterr()
    assert main(["doctor", "--dry-run", "-C", str(ctx.root), "--no-color"]) == 0
    assert "Agent Skill copies checked: ~/.claude/skills/grove" in capsys.readouterr().out
