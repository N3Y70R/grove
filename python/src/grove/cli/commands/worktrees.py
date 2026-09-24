"""Worktree lifecycle: list, create, track, remove."""

from __future__ import annotations

import argparse
from pathlib import Path

from ...core import config as core_config
from ...core.errors import UsageError
from ...core.model import Worktree, list_worktrees, worktree_dict
from ..output import Output
from .._shared import _common, _enter_repo, _make_runner


def _truncate(s: str, width: int) -> str:
    return s if len(s) <= width else s[: width - 1] + "…"


def _status_str(wt: Worktree) -> str:
    if wt.is_bare:
        return "(bare)"
    if not wt.exists:
        return "missing"
    if wt.upstream is None:
        clean = "dirty" if wt.dirty else "clean"
        merged = " merged" if wt.merged else ""
        if wt.compared_to:
            return (f"↑{wt.ahead or 0} ↓{wt.behind or 0} vs {wt.compared_to} "
                    f"(no upstream) {clean}{merged}")
        return f"no-upstream {clean}{merged}"
    clean = "dirty" if wt.dirty else "clean"
    merged = " merged" if wt.merged else ""
    return f"↑{wt.ahead or 0} ↓{wt.behind or 0} {clean}{merged}"


def cmd_list(args, out: Output) -> int:
    git = _make_runner(args, out)
    repo = _enter_repo(args)
    wts = list_worktrees(git, repo, with_status=True)

    # Filters.
    def keep(wt: Worktree) -> bool:
        if args.orphans and not (wt.prunable or not wt.exists):
            return False
        if args.dirty and not wt.dirty:
            return False
        if args.type:
            cls = wt.classification
            kind = cls.kind if cls else None
            typ = cls.type if cls else None
            if args.type not in (kind, typ):
                return False
        return True

    rows = [wt for wt in wts if keep(wt)]

    if out.json_mode:
        out.set_result([worktree_dict(wt) for wt in rows])
        out.success(f"{len(rows)} worktree(s)")
        return 0

    if not rows:
        out.plain("(no worktrees)")
        return 0

    # Table.
    PATHW, BRANCHW = 45, 45
    headers = ("FOLDER", "BRANCH", "TICKET", "STATUS")
    table = []
    for wt in rows:
        carpeta = "(bare)" if wt.is_bare else wt.rel_path
        rama = wt.branch or ("(detached)" if wt.is_detached else "—")
        ticket = (wt.classification.ticket if wt.classification and wt.classification.ticket else "—")
        table.append((
            _truncate(carpeta, PATHW),
            _truncate(rama, BRANCHW),
            ticket,
            _status_str(wt),
        ))

    w0 = max(len(headers[0]), *(len(r[0]) for r in table))
    w1 = max(len(headers[1]), *(len(r[1]) for r in table))
    w2 = max(len(headers[2]), *(len(r[2]) for r in table))
    fmt = f"{{:<{w0}}}  {{:<{w1}}}  {{:<{w2}}}  {{}}"
    out.plain(fmt.format(*headers))
    for r in table:
        out.plain(fmt.format(*r))
    return 0


def _finish_create(args, out: Output, repo, path) -> int:
    rel = None
    try:
        rel = str(Path(path).relative_to(repo.root)).replace("\\", "/")
    except (ValueError, AttributeError):
        rel = str(path)
    out.set_result({"path": str(path), "rel_path": rel, "branch": rel})
    if getattr(args, "print_path", False) and not out.json_mode:
        # Only the path on stdout, for `cd "$(gwt create ... --print-path)"`.
        print(str(path))
        return 0
    out.success(f"Worktree created: {path}")
    return 0


def cmd_create(args, out: Output) -> int:
    from ...core import create as core_create

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    params = args.params
    kind = params[0]

    if kind == "release":
        if len(params) < 2:
            raise UsageError("Usage: gwt create release <version> [--base <branch>]")
        path = core_create.create_release(
            git, repo, version=params[1], base=args.base, step=out.step
        )
    elif kind == "temp":
        if len(params) < 2:
            raise UsageError("Usage: gwt create temp <name>")
        path = core_create.create_temp(git, repo, name=params[1], base=args.base, step=out.step)
    else:
        ticket, type_, desc = _parse_ticket_form(params)
        path = core_create.create_ticket(
            git, repo,
            type=type_, name=desc, ticket=ticket,
            base=args.base, step=out.step,
        )
    return _finish_create(args, out, repo, path)


def _parse_ticket_form(params):
    """Interprets the 'create' args according to the repo's ticket policy.

    required: <TICKET> <type> "<desc>"
    off:      <type> "<desc>"
    optional: detects whether the first arg is a ticket key.
    """
    mode = core_config.TICKETS
    has_ticket = bool(params) and core_config.TICKET_RE.fullmatch(params[0]) is not None

    if mode == "off" or (mode == "optional" and not has_ticket):
        if len(params) < 2:
            raise UsageError('Usage (without ticket): gwt create <type> "<name>"')
        return None, params[0], params[1]

    # required, or optional with a detected key.
    if len(params) < 3:
        raise UsageError('Usage: gwt create <TICKET-ID> <type> "<name>"')
    return params[0], params[1], params[2]


def cmd_track(args, out: Output) -> int:
    from ...core import track as core_track

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    path = core_track.track(
        git, repo, branch=args.origin_branch, as_=args.as_, step=out.step, warn=out.warn
    )
    out.set_result({"path": str(path), "branch": args.origin_branch})
    out.success(f"Branch brought in: {path}")
    return 0


def cmd_remove(args, out: Output) -> int:
    from ...core import remove as core_remove

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    suffix = " (dry-run)" if getattr(args, "dry_run", False) else ""

    if args.merged:
        removed = core_remove.sweep_merged(
            git, repo, delete_branch=args.delete_branch, force=args.force, step=out.step
        )
        out.set_result({"mode": "merged", "removed": [w.rel_path for w in removed],
                        "dry_run": getattr(args, "dry_run", False)})
        if not removed:
            out.success("There are no ticket worktrees merged into the base to remove.")
        else:
            out.success(f"{len(removed)} worktree(s) removed{suffix}: "
                        + ", ".join(w.rel_path for w in removed))
        return 0

    if not args.target:
        raise UsageError("Specify a target (ticket, branch or path) or use --merged.")

    wt = core_remove.resolve_target(git, repo, args.target)
    core_remove.remove_one(
        git, repo, wt, delete_branch=args.delete_branch, force=args.force, step=out.step
    )
    out.set_result({"mode": "single", "removed": [wt.rel_path],
                    "delete_branch": args.delete_branch,
                    "dry_run": getattr(args, "dry_run", False)})
    out.success(f"Worktree removed{suffix}: {wt.rel_path}")
    return 0


def register_list(sub) -> None:
    lp = sub.add_parser("list", help="list the repo's worktrees")
    _common(lp)
    lp.add_argument("--type", help="filter by type/kind")
    lp.add_argument("--dirty", action="store_true", help="only worktrees with changes")
    lp.add_argument("--orphans", action="store_true", help="only orphan/prunable")
    lp.set_defaults(func=cmd_list)


def register_create(sub) -> None:
    cp = sub.add_parser(
        "create",
        help="create a ticket / release / temp worktree",
        description=(
            'gwt create <TICKET-ID> <feature|hotfix|bugfix> "<name>"\n'
            "gwt create release <version>\n"
            "gwt create temp <name>"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _common(cp)
    cp.add_argument("params", nargs="+", help="arguments per the subform (see description)")
    cp.add_argument("--base", help="base branch (default: the repo's)")
    cp.add_argument("--print-path", dest="print_path", action="store_true",
                    help="print only the created path")
    cp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    cp.set_defaults(func=cmd_create)


def register_track(sub) -> None:
    tp = sub.add_parser("track", help="bring an existing branch (local or from origin) into the structure")
    _common(tp)
    tp.add_argument("origin_branch", metavar="branch",
                    help="branch name (local or from origin)")
    tp.add_argument("--as", dest="as_", metavar="TYPE/TICKET-XXXXX-slug",
                    help="explicit destination to relocate or force a type")
    tp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    tp.set_defaults(func=cmd_track)


def register_remove(sub) -> None:
    rp = sub.add_parser("remove", aliases=["rm"], help="remove a worktree safely")
    _common(rp)
    rp.add_argument("target", nargs="?", help="ticket, branch or path of the worktree")
    rp.add_argument("--delete-branch", dest="delete_branch", action="store_true",
                    help="also delete the local branch (if merged/pushed)")
    rp.add_argument("--force", action="store_true",
                    help="remove even if dirty; delete the branch even if not merged")
    rp.add_argument("--merged", action="store_true",
                    help="sweep all ticket worktrees merged into the base")
    rp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    rp.set_defaults(func=cmd_remove)
