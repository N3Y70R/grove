"""Remote interaction: reset (ex-sync), fetch, compare, publish."""

from __future__ import annotations

from pathlib import Path

from ...core import config as core_config
from ...core.errors import UsageError
from ..output import Output
from .._shared import _common, _enter_repo, _make_runner


def cmd_reset(args, out: Output) -> int:
    from ...core import sync as core_sync
    from ...core.model import list_worktrees as _lw

    if getattr(args, "command", None) == "sync":
        out.warn("'gwt sync' is deprecated and will be removed; use 'gwt reset' "
                 "(same behavior: it DISCARDS local commits and changes). "
                 "To only bring remote changes, use 'gwt fetch'.")
    git = _make_runner(args, out)
    repo = _enter_repo(args)

    # Resolve target (with status, to warn about losses).
    if args.target:
        from ...core import remove as core_remove
        wt = core_remove.resolve_target(git, repo, args.target)
    else:
        cwd = Path.cwd().resolve()
        wt = None
        for w in _lw(git, repo, with_status=True):
            if w.is_bare:
                continue
            try:
                cwd.relative_to(w.path.resolve())
                wt = w
                break
            except ValueError:
                continue
        if wt is None:
            raise UsageError("Specify the worktree to reset (not detected from the current directory).")

    # Destructive warning.
    losses = core_sync.reset_losses(wt)
    if losses and not args.yes and not getattr(args, "dry_run", False):
        if out.json_mode:
            raise UsageError(
                f"reset would discard in {wt.rel_path}: {', '.join(losses)}. "
                f"In --json mode use --yes to confirm."
            )
        out.warn(f"reset will discard in {wt.rel_path}: {', '.join(losses)}.")
        try:
            ans = input("Continue? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            out.plain("Cancelled.")
            return 0

    core_sync.reset_worktree(git, repo, wt, clean=args.clean, step=out.step)
    suffix = " (dry-run)" if getattr(args, "dry_run", False) else ""
    out.set_result({"worktree": wt.rel_path, "discarded": losses,
                    "dry_run": getattr(args, "dry_run", False)})
    out.success(f"Worktree reset to origin{suffix}: {wt.rel_path}")
    return 0


def cmd_publish(args, out: Output) -> int:
    from ...core import publish as core_publish

    git = _make_runner(args, out)
    repo = _enter_repo(args)

    integration = args.into or core_config.INTEGRATION_BRANCH
    if not integration:
        raise UsageError("No integration branch configured. Use --into <branch>.")

    dry_run = getattr(args, "dry_run", False)
    suffix = " (dry-run)" if dry_run else ""

    if not args.targets and not args.regenerate:
        raise UsageError(
            "Specify at least one ticket/branch to publish, or use "
            "--regenerate --base <branch> to create the integration branch."
        )

    base = args.base or core_config.DEFAULT_BASE
    branches = [core_publish.resolve_branch(git, repo, t) for t in args.targets]
    # In regenerate mode, allow creating the integration branch from base if missing.
    int_path, created = core_publish.ensure_integration(
        git, repo, integration,
        create_base=(base if args.regenerate else None), step=out.step,
    )

    if args.regenerate and not created:
        # Rebuilding an existing branch → force-push → confirm.
        if not args.yes and not dry_run:
            if out.json_mode:
                raise UsageError(
                    f"--regenerate will force-push to origin/{integration}. "
                    f"In --json mode use --yes to confirm."
                )
            out.warn(f"--regenerate will rewrite origin/{integration} with a force-push "
                     f"(from {base} + {len(branches)} branch/es).")
            try:
                ans = input("Continue? [y/N] ").strip().lower()
            except EOFError:
                ans = ""
            if ans not in ("y", "yes"):
                out.plain("Cancelled.")
                return 0
        core_publish.publish_regenerate(
            git, repo, integration, int_path, branches, base=base, step=out.step
        )
        mode = "regenerate"
    elif args.regenerate and created:
        # Freshly created from base → merge any targets and normal push (nothing to overwrite).
        core_publish.publish_additive(
            git, repo, integration, int_path, branches, no_sync=True, step=out.step
        )
        mode = "created"
    else:
        core_publish.publish_additive(
            git, repo, integration, int_path, branches, no_sync=args.no_sync, step=out.step
        )
        mode = "additive"

    out.set_result({"integration": integration, "mode": mode, "created": created,
                    "branches": branches, "base": base, "dry_run": dry_run})
    verb = "Created" if created else "Published"
    out.success(f"{verb}{suffix} {integration}: {', '.join(branches) or '(no targets)'}")
    return 0


def _cwd_branch(git, repo):
    """Branch of the worktree containing the current directory, or None."""
    from ...core.model import list_worktrees as _lw
    cwd = Path.cwd().resolve()
    for w in _lw(git, repo, with_status=False):
        if w.is_bare or not w.branch:
            continue
        try:
            cwd.relative_to(w.path.resolve())
            return w.branch
        except ValueError:
            continue
    return None


def cmd_fetch(args, out: Output) -> int:
    from ...core import fetch as core_fetch

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    rows = core_fetch.fetch(git, repo, prune=args.prune, step=out.step)
    behind = [r for r in rows if r["behind"]]
    if out.json_mode:
        out.set_result({"prune": args.prune, "worktrees": rows})
        out.success(f"Fetched from origin; {len(behind)} worktree(s) behind")
        return 0
    out.success("Fetched from origin (worktrees untouched)")
    if rows:
        w0 = max(len("WORKTREE"), *(len(r["worktree"]) for r in rows))
        out.plain(f"  {'WORKTREE':<{w0}}   STATUS")
        for r in rows:
            if r["ahead"] is None:
                status = "no upstream"
            else:
                status = f"↑{r['ahead']} ↓{r['behind']} vs {r['compared_to']}  {r['status']}"
            dirty = "  (dirty)" if r["dirty"] else ""
            out.plain(f"  {r['worktree']:<{w0}}   {status}{dirty}")
    if behind:
        out.plain("To bring a worktree up to date: cd <worktree> && git merge --ff-only "
                  "(or git pull). grove never changes your worktrees on fetch.")
    return 0


def cmd_compare(args, out: Output) -> int:
    from ...core import compare as core_compare

    git = _make_runner(args, out)
    repo = _enter_repo(args)

    if args.fetch:
        out.step("Updating from origin (fetch)")
        git.run(["fetch", "origin"], cwd=repo.bare)

    if args.vs:
        ref_label, rows = core_compare.compare_all_vs(git, repo, args.vs)
        if out.json_mode:
            out.set_result({"vs": ref_label, "rows": rows})
            out.success(f"{len(rows)} worktree(s) compared against {ref_label}")
            return 0
        out.plain(f"Worktrees vs {ref_label}:")
        if not rows:
            out.plain("  (no worktrees)")
            return 0
        w0 = max(len("WORKTREE"), *(len(r["a"]) for r in rows))
        out.plain(f"  {'WORKTREE':<{w0}}   STATUS")
        for r in rows:
            out.plain(f"  {r['a']:<{w0}}   ↑{r['ahead']} ↓{r['behind']}  {r['status']}")
        return 0

    cwd_branch = None if args.a else _cwd_branch(git, repo)
    res = core_compare.compare_one(git, repo, args.a, args.b, cwd_branch=cwd_branch)
    if out.json_mode:
        out.set_result(res)
        out.success(f"{res['a']} vs {res['b']}: ↑{res['ahead']} ↓{res['behind']} ({res['status']})")
        return 0
    out.plain(f"{res['a']}  ↑{res['ahead']} ↓{res['behind']}  "
              f"({res['status']} relative to {res['b']})")
    return 0


def register_publish(sub) -> None:
    pp = sub.add_parser("publish", help="bring branches into the shared integration branch")
    _common(pp)
    pp.add_argument("targets", nargs="*",
                    help="tickets or branches to publish (optional with --regenerate)")
    pp.add_argument("--into", help="integration branch (default: config integration_branch)")
    pp.add_argument("--regenerate", action="store_true",
                    help="regenerate the integration branch from the base (force-push)")
    pp.add_argument("--base", help="base for --regenerate (default: repo base branch)")
    pp.add_argument("--no-sync", dest="no_sync", action="store_true",
                    help="additive mode: do not sync the integration branch before merging")
    pp.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    pp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what it would do without executing")
    pp.set_defaults(func=cmd_publish)


def register_reset(sub) -> None:
    syp = sub.add_parser(
        "reset", aliases=["sync"],
        help="DISCARD local commits/changes: reset a worktree to its origin branch "
             "(reset --hard). 'sync' is a deprecated alias")
    _common(syp)
    syp.add_argument("target", nargs="?", help="ticket, branch or path (default: current worktree)")
    syp.add_argument("--clean", action="store_true", help="also delete untracked files")
    syp.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    syp.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="show what it would do without executing")
    syp.set_defaults(func=cmd_reset)


def register_fetch(sub) -> None:
    fp = sub.add_parser(
        "fetch",
        help="bring what's new on origin and show each worktree's ahead/behind "
             "(safe: never touches your worktrees)")
    _common(fp)
    fp.add_argument("--prune", action="store_true",
                    help="also drop origin/* refs of branches deleted on the remote")
    fp.set_defaults(func=cmd_fetch)


def register_compare(sub) -> None:
    mp = sub.add_parser(
        "compare",
        help="ahead/behind between branches/worktrees; --fetch first brings remote "
             "changes (safe: never touches your worktrees)")
    _common(mp)
    mp.add_argument("a", nargs="?", help="worktree/branch A (default: current worktree)")
    mp.add_argument("b", nargs="?", help="worktree/branch B (default: upstream of A)")
    mp.add_argument("--vs", metavar="REF", help="compare ALL worktrees against REF")
    mp.add_argument("--fetch", action="store_true",
                    help="git fetch origin first (the safe way to bring remote changes)")
    mp.set_defaults(func=cmd_compare)
