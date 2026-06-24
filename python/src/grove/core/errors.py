"""Core exceptions, mapped to exit codes in the CLI."""

from __future__ import annotations


class WtError(Exception):
    """Base error. exit_code defines the process exit code."""

    exit_code = 1


class ValidationError(WtError):
    """Convention violation / invalid arguments."""

    exit_code = 1


class GitError(WtError):
    """A git command failed."""

    exit_code = 2


class UsageError(WtError):
    """Incorrect usage (context, flags)."""

    exit_code = 3
