"""Setup operation: initializes a repo with the bare + production + parking model."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from . import config
from .errors import UsageError, ValidationError
from .gitrunner import GitRunner
from .repo import RepoContext, write_git_pointer


def derive_name(url: str) -> str:
    """Derives the folder name from the origin URL."""
    tail = re.split(r"[\\/]", url.rstrip("/"))[-1]
    if tail.endswith(".git"):
        tail = tail[: -len(".git")]
    if not tail:
        raise ValidationError(f"Could not derive a name from the URL: {url}")
    return tail


def setup(
    git: GitRunner,
    url: str,
    *,
    into: Path,
    name: Optional[str] = None,
    base_branch: str = config.DEFAULT_BASE,
    git_pointer: bool = True,
    keep_on_error: bool = False,
    step=lambda msg: None,
) -> RepoContext:
    """Creates <into>/<name> with .bare/ and the production/ worktree.

    'step' is an optional callback to report progress (provided by the CLI).

    Transactional: if any step fails after the destination is created, the
    partial <name>/ folder is removed so a retry starts clean. Pass
    ``keep_on_error=True`` to leave the partial state in place for debugging.
    """
    name = name or derive_name(url)
    root = Path(into).resolve() / name
    bare = root / ".bare"

    if root.exists():
        raise UsageError(f"The destination already exists: {root}")

    try:
        return _setup_inner(git, url, root, bare, name, base_branch, git_pointer, step)
    except BaseException:
        # The destination did not exist before us, so anything at 'root' now is
        # our partial work: clean it up so the next attempt isn't blocked.
        if not keep_on_error and root.exists():
            step(f"Setup failed — cleaning up partial {name}/")
            shutil.rmtree(root, ignore_errors=True)
        raise


def _setup_inner(git, url, root, bare, name, base_branch, git_pointer, step) -> RepoContext:
    step(f"Cloning bare into {name}/.bare")
    git.run(["clone", "--bare", url, str(bare)], cwd=None)

    step("Configuring origin refspec")
    git.run(["config", "remote.origin.fetch", config.ORIGIN_REFSPEC], cwd=bare)
    git.run(["fetch", "origin"], cwd=bare)

    # So that the first push of new branches creates the same-named branch on origin.
    git.run(["config", "push.default", "current"], cwd=bare)

    # Origin's default branch: HEAD of the fresh bare clone points to it.
    detected = git.run(
        ["symbolic-ref", "--short", "HEAD"], cwd=bare, check=False, mutating=False
    ).stdout.strip()

    # Verifies that the base branch exists locally after the clone. If not, fall
    # back to origin's detected default (e.g. profile says 'main' but the repo
    # uses 'production').
    if not git.ok(["rev-parse", "--verify", f"refs/heads/{base_branch}"], cwd=bare):
        if detected and git.ok(["rev-parse", "--verify", f"refs/heads/{detected}"], cwd=bare):
            step(f"Base branch '{base_branch}' not found on origin; "
                 f"using origin's default '{detected}'")
            base_branch = detected
        else:
            raise ValidationError(
                f"Origin does not have the base branch '{base_branch}'; it cannot be initialized."
            )

    step(f"Creating parking branch {config.PARKING_BRANCH} (base {base_branch})")
    git.run(["branch", config.PARKING_BRANCH, base_branch], cwd=bare)
    git.run(["symbolic-ref", "HEAD", f"refs/heads/{config.PARKING_BRANCH}"], cwd=bare)

    step(f"Creating worktree {base_branch}/ (origin/{base_branch})")
    prod_path = root / base_branch
    git.run(["worktree", "add", str(prod_path), base_branch], cwd=bare)
    git.run(
        ["branch", f"--set-upstream-to=origin/{base_branch}", base_branch],
        cwd=prod_path,
    )

    # Local artifacts folder (not a worktree; never versioned or pushed).
    if config.ARTIFACTS_DIR:
        step(f"Creating local artifacts folder {config.ARTIFACTS_DIR}/")
        (root / config.ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)

    # Root .git pointer so plain `git` works from the repo root.
    if git_pointer and write_git_pointer(root):
        step("Writing root .git pointer (gitdir: ./.bare)")

    return RepoContext(root=root, bare=bare, name=name, base=base_branch)
