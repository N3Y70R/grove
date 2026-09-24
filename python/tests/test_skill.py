"""0.12.0 — grove's Agent Skill (skills/grove) and `gwt skill install`."""

import json
import re
from pathlib import Path

import pytest

import grove
from grove.core import skill as core_skill
from grove.core.errors import ValidationError

REPO_SKILL = Path(__file__).resolve().parents[2] / "skills" / "grove"


def _frontmatter(text):
    assert text.startswith("---\n")
    head, body = text[4:].split("\n---\n", 1)
    meta, key = {}, None
    for line in head.splitlines():
        if line.startswith("  ") and key:                     # nested map (metadata)
            k, v = line.strip().split(":", 1)
            meta.setdefault(key, {})[k.strip()] = v.strip().strip('"')
        else:
            k, v = line.split(":", 1)
            key = k.strip()
            if v.strip():
                meta[key] = v.strip()
    return meta, body


def test_skill_follows_the_agent_skills_spec():
    text = (core_skill.bundled_dir() / "SKILL.md").read_text(encoding="utf-8")
    meta, body = _frontmatter(text)
    name = meta["name"]
    assert name == core_skill.bundled_dir().name == "grove"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert 0 < len(meta["description"]) <= 1024
    assert len(meta.get("compatibility", "")) <= 500
    assert len(text.splitlines()) < 500                       # spec: SKILL.md < 500 lines
    for ref in re.findall(r"\]\((references/[^)]+)\)", body):
        assert (core_skill.bundled_dir() / ref).is_file(), ref
        assert ref.count("/") == 1                           # one level deep


def test_skill_version_matches_grove():
    meta, _ = _frontmatter((core_skill.bundled_dir() / "SKILL.md").read_text(encoding="utf-8"))
    assert meta["metadata"]["grove-version"] == grove.__version__


@pytest.mark.skipif(not REPO_SKILL.is_dir(), reason="repo checkout not available (e.g. sdist)")
def test_packaged_skill_matches_the_repo_copy():
    repo = {p.relative_to(REPO_SKILL): p.read_bytes() for p in REPO_SKILL.rglob("*") if p.is_file()}
    pkg = {p.relative_to(core_skill.bundled_dir()): p.read_bytes()
           for p in core_skill.bundled_dir().rglob("*") if p.is_file()}
    assert repo == pkg, "skills/grove and python/src/grove/_skill/grove differ: " \
                        "copy skills/grove over python/src/grove/_skill/grove"


def test_install_is_idempotent_and_safe(tmp_path):
    root = tmp_path / "skills"
    res = core_skill.install(dest_root=root)
    assert res["mode"] == "created" and Path(res["path"]) == root / "grove"
    assert (root / "grove" / "SKILL.md").is_file()
    assert "references/troubleshooting.md" in res["files"]
    assert core_skill.install(dest_root=root)["mode"] == "unchanged"

    (root / "grove" / "SKILL.md").write_text("edited\n", encoding="utf-8")
    with pytest.raises(ValidationError):                     # never overwrite silently
        core_skill.install(dest_root=root)
    assert (root / "grove" / "SKILL.md").read_text() == "edited\n"
    assert core_skill.install(dest_root=root, force=True)["mode"] == "updated"
    assert (root / "grove" / "SKILL.md").read_bytes() == \
        (core_skill.bundled_dir() / "SKILL.md").read_bytes()


def test_install_dry_run_writes_nothing(tmp_path):
    res = core_skill.install(dest_root=tmp_path / "skills", dry_run=True)
    assert res["dry_run"] is True and res["mode"] == "created"
    assert not (tmp_path / "skills").exists()


def test_install_targets(tmp_path, monkeypatch, repo):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    assert core_skill.target_root("agents") == tmp_path / "home" / ".agents" / "skills"
    assert core_skill.target_root("claude") == tmp_path / "home" / ".claude" / "skills"
    git, ctx = repo
    wt = ctx.root / "main"
    assert core_skill.target_root("project", cwd=wt) == wt / ".agents" / "skills"
    with pytest.raises(ValidationError):
        core_skill.target_root("project", cwd=tmp_path)       # not inside a git worktree


def test_cli_and_mcp_install(tmp_path, capsys):
    from grove.cli.main import main
    from grove.mcp import _ops
    dest = tmp_path / "s"
    assert main(["skill", "install", "--path", str(dest), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["mode"] == "created"
    assert _ops.op_skill_install(path=str(dest))["mode"] == "unchanged"
