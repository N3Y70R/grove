"""0.7.1 — discoverability: `grove` entry point, `setup` pointing at `convert`,
`adopt` alias, version visible from config/doctor."""

import json
import subprocess
from pathlib import Path

import pytest

import grove
from grove.core import setup as core_setup
from grove.core.errors import UsageError
from grove.core.gitrunner import GitRunner

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover (py3.10 dev envs)
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_grove_entry_point_is_an_alias_of_gwt():
    scripts = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["grove"] == scripts["gwt"] == "grove.cli.main:main"


def test_setup_into_existing_clone_suggests_convert(origin, tmp_path):
    dest = tmp_path / "work" / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(dest)], check=True)
    with pytest.raises(UsageError) as exc:
        core_setup.setup(GitRunner(), str(origin), into=tmp_path / "work", name="repo",
                         base_branch="main")
    assert "gwt convert" in str(exc.value)
    assert (dest / ".git").is_dir()                          # untouched


def test_setup_into_existing_plain_dir_does_not_suggest_convert(origin, tmp_path):
    (tmp_path / "work" / "repo").mkdir(parents=True)
    with pytest.raises(UsageError) as exc:
        core_setup.setup(GitRunner(), str(origin), into=tmp_path / "work", name="repo",
                         base_branch="main")
    assert "already exists" in str(exc.value)
    assert "convert" not in str(exc.value)


def test_adopt_is_an_alias_of_convert(origin, tmp_path, capsys):
    from grove.cli.main import main
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    assert main(["adopt", str(clone), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["dry_run"] is True
    assert not (clone / ".bare").exists()


def test_version_in_mcp_config_and_doctor(repo):
    from grove.mcp import _ops
    git, ctx = repo
    assert _ops.op_config_show(cwd=str(ctx.root))["version"] == grove.__version__
    assert _ops.op_doctor(cwd=str(ctx.root))["version"] == grove.__version__


def test_version_in_cli_json(repo, capsys, monkeypatch):
    from grove.cli.main import main
    git, ctx = repo
    monkeypatch.chdir(ctx.root)
    for argv in (["config", "show", "--json"], ["doctor", "--json"]):
        assert main(argv) == 0
        assert json.loads(capsys.readouterr().out)["result"]["version"] == grove.__version__
