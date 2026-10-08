"""Validate release metadata without importing Grove or third-party packages."""
import ast
import re
import sys
import tomllib
from pathlib import Path


def check(root: Path, tag: str) -> str:
    match = re.fullmatch(r"python/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag)
    if not match:
        raise ValueError("Expected a stable Python release tag: python/vX.Y.Z")
    version = tag.removeprefix("python/v")
    metadata = tomllib.loads((root / "python/pyproject.toml").read_text())
    values = {"package": metadata["project"]["version"]}
    tree = ast.parse((root / "python/src/grove/__init__.py").read_text())
    values["runtime"] = next(ast.literal_eval(node.value) for node in tree.body
                             if isinstance(node, ast.Assign) and
                             any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets))
    for name in ("skills/grove/SKILL.md", "python/src/grove/_skill/grove/SKILL.md"):
        text = (root / name).read_text()
        skill = re.search(r'^  grove-version: "([^"\n]+)"$', text, re.M)
        values[name] = skill.group(1) if skill else None
    inconsistent = {key: value for key, value in values.items() if value != version}
    if inconsistent:
        raise ValueError(f"Release {version} has inconsistent metadata: {inconsistent}")
    if f"## python — {version}\n" not in (root / "CHANGELOG.md").read_text():
        raise ValueError(f"Missing Python {version} changelog entry")
    return version


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Usage: check-python-release.py python/vX.Y.Z")
        print(check(Path(__file__).resolve().parents[1], sys.argv[1]))
    except (ValueError, StopIteration) as exc:
        sys.exit(str(exc))
