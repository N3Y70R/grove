"""The tag must describe exactly the package that will be published."""
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
check = runpy.run_path(str(ROOT / 'scripts/check-python-release.py'))['check']


def test_current_release_metadata_matches():
    from grove import __version__
    assert check(ROOT, f'python/v{__version__}') == __version__


@pytest.mark.parametrize('tag', ['v0.16.0', 'python/v0.16', 'python/v01.16.0', 'python/v0.16.0rc1'])
def test_release_rejects_noncanonical_tag(tag):
    with pytest.raises(ValueError, match='stable Python release tag'):
        check(ROOT, tag)


def test_release_rejects_mismatched_version():
    with pytest.raises(ValueError, match='inconsistent metadata'):
        check(ROOT, 'python/v0.0.0')


def test_release_requires_versioned_changelog(tmp_path):
    for name in ['python/pyproject.toml', 'python/src/grove/__init__.py',
                 'skills/grove/SKILL.md', 'python/src/grove/_skill/grove/SKILL.md']:
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / name).read_bytes())
    (tmp_path / 'CHANGELOG.md').write_text('## python — Unreleased\n')
    from grove import __version__
    with pytest.raises(ValueError, match='Missing.*changelog'):
        check(tmp_path, f'python/v{__version__}')
