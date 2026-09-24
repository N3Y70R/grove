"""Helpers shared by the CLI command modules."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from ..core import config as core_config
from ..core.gitrunner import GitRunner
from ..core.repo import find_repo, RepoContext
from .output import Output


def _enter_repo(args) -> RepoContext:
    """Locates the managed repo and loads its policy (grove.toml)."""
    repo = find_repo(_base_dir(args))
    core_config.load(repo.bare)
    return repo


def _make_runner(args, out: Output) -> GitRunner:
    confirm = out.confirm_git if getattr(args, "confirm_each", False) else None
    return GitRunner(
        on_command=out.git_echo,
        confirm=confirm,
        dry_run=getattr(args, "dry_run", False),
    )


def _base_dir(args) -> Path:
    return Path(args.C).resolve() if getattr(args, "C", None) else Path.cwd()


def _origin_of(repo) -> Optional[str]:
    git = GitRunner()
    res = git.run(["remote", "get-url", "origin"], cwd=repo.bare, check=False, mutating=False)
    return res.stdout.strip() if res.returncode == 0 else None


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    parser.add_argument("-v", "--verbose", action="store_true", help="print each git command")
    parser.add_argument("--confirm-each", dest="confirm_each", action="store_true",
                        help="ask for confirmation before each git command (implies -v)")
    parser.add_argument("--no-color", dest="no_color", action="store_true", help="no colors")
    parser.add_argument("--json", action="store_true",
                        help="JSON output with status, reason and result data")
    parser.add_argument("-C", metavar="PATH", help="run as if the cwd were PATH")
