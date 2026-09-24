"""Entry point of the `gwt` CLI.

The commands live in `grove.cli.commands` (one module per area); this
module builds the parser — registering them in the order shown by
`gwt --help` — and runs the selected handler."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from ..core.errors import WtError
from .commands import maintenance, remote, repo, ssh, worktrees
from .output import Output


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gwt", description="grove — git worktree management with a convention. "
                                "The command is `gwt` (also installed as `grove`).")
    p.add_argument("--version", action="store_true", help="show the version and exit")
    sub = p.add_subparsers(dest="command")

    repo.register_setup(sub)
    repo.register_convert(sub)
    worktrees.register_list(sub)
    worktrees.register_create(sub)
    worktrees.register_start(sub)
    worktrees.register_track(sub)
    maintenance.register_doctor(sub)
    worktrees.register_remove(sub)
    remote.register_publish(sub)
    remote.register_reset(sub)
    remote.register_fetch(sub)
    remote.register_compare(sub)
    maintenance.register_patch(sub)
    maintenance.register_artifacts(sub)
    repo.register_config(sub)
    ssh.register_ssh(sub)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "version", False):
        from .. import __version__
        print(f"grove (gwt) {__version__}")
        return 0

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    verbose = getattr(args, "verbose", False) or getattr(args, "confirm_each", False)
    json_mode = getattr(args, "json", False)
    # --print-path must leave only the path on stdout: silence the steps.
    quiet = getattr(args, "quiet", False) or getattr(args, "print_path", False)
    out = Output(
        quiet=quiet,
        no_color=getattr(args, "no_color", False),
        verbose=verbose,
        json_mode=json_mode,
    )
    command = getattr(args, "command", None)

    def _emit(envelope: dict) -> None:
        print(json.dumps(envelope, indent=2, ensure_ascii=False))

    try:
        rc = args.func(args, out)
        if json_mode:
            _emit({
                "command": command,
                "status": "ok",
                "exit_code": rc,
                "message": out.message,
                "result": out.result,
                "log": out.log,
            })
        return rc
    except WtError as e:
        if json_mode:
            _emit({
                "command": command,
                "status": "error",
                "exit_code": e.exit_code,
                "error_type": type(e).__name__,
                "message": str(e),
                "log": out.log,
            })
        else:
            out.error(str(e))
        return e.exit_code
    except KeyboardInterrupt:
        if json_mode:
            _emit({"command": command, "status": "error", "exit_code": 130,
                   "error_type": "KeyboardInterrupt", "message": "Interrupted.", "log": out.log})
        else:
            out.error("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
