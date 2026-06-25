"""Worktree creation operations: ticket, release and temp."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import config, naming, ops
from .errors import ValidationError
from .gitrunner import GitRunner
from .repo import RepoContext

Step = ops.Step


def create_ticket(
    git: GitRunner,
    repo: RepoContext,
    *,
    type: str,
    name: str,
    ticket: Optional[str] = None,
    base: Optional[str] = None,
    step: Step = lambda m: None,
) -> Path:
    if type not in config.TICKET_TYPES:
        raise ValidationError(
            f"Type '{type}' not allowed. Valid types: {', '.join(config.TICKET_TYPES)}."
        )

    # Ticket policy.
    norm_ticket: Optional[str] = None
    if config.TICKETS == "off":
        if ticket:
            raise ValidationError("This repo is in 'tickets = off' mode; keys are not accepted.")
    else:  # required | optional
        if ticket:
            norm_ticket = naming.extract_ticket(ticket)
            if not norm_ticket:
                if config.TICKET_PREFIXES:
                    claves = ", ".join(f"{p}-XXXX" for p in config.TICKET_PREFIXES)
                    detalle = f"Accepted keys: {claves}."
                else:
                    detalle = "It must contain a ticket key (e.g. ABC-123)."
                raise ValidationError(f"Invalid ticket '{ticket}'. {detalle}")
        elif config.TICKETS == "required":
            raise ValidationError("This repo requires a ticket key (tickets = required).")

    slug = naming.slugify(name)
    if not slug:
        raise ValidationError("The name did not produce a valid slug.")

    if norm_ticket:
        rel_path = f"{type}/{norm_ticket}-{slug}"
    else:
        rel_path = f"{type}/{slug}"
    branch = rel_path  # folder ↔ branch
    base = base or config.DEFAULT_BASE

    step(f"slug: {slug}")
    check = "ticket folder=branch ✓" if norm_ticket else "no ticket"
    step(f"Validating: type {type} ✓ · {check}")
    return ops.add_new(git, repo, branch=branch, rel_path=rel_path, base=base, step=step)


def create_release(
    git: GitRunner,
    repo: RepoContext,
    *,
    version: str,
    base: Optional[str] = None,
    step: Step = lambda m: None,
) -> Path:
    branch = config.RELEASE_FORMAT.format(version=version)  # release/<version>
    rel_path = branch

    if ops.origin_branch_exists(git, repo, branch):
        step(f"origin/{branch} exists -> fetching existing version")
        return ops.bring(
            git, repo, origin_branch=branch, local_branch=branch, rel_path=rel_path, step=step
        )

    base = base or config.RELEASE_DEFAULT_BASE
    step(f"Checking collision: origin does not have {branch} ✓")
    return ops.add_new(git, repo, branch=branch, rel_path=rel_path, base=base, step=step)


def create_temp(
    git: GitRunner,
    repo: RepoContext,
    *,
    name: str,
    base: Optional[str] = None,
    step: Step = lambda m: None,
) -> Path:
    safe = naming.slugify(name)
    if not safe:
        raise ValidationError(f"Invalid temporary name: '{name}'.")
    rel_path = f"{config.TEMP_DIR}/{safe}"
    branch = rel_path  # ephemeral branch with the same name
    return ops.add_new(
        git, repo, branch=branch, rel_path=rel_path,
        base=base or config.DEFAULT_BASE, step=step,
    )
