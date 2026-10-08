"""Hygiene and local tooling: doctor, patch, artifacts."""

from __future__ import annotations

from pathlib import Path

from ...core import config as core_config
from ...core.errors import WtError, UsageError
from ...core.gitrunner import GitRunner
from ..output import Output
from .._shared import _common, _enter_repo, _make_runner, _base_dir


def cmd_doctor(args, out: Output) -> int:
    from ...core import doctor as core_doctor
    git = _make_runner(args, out)
    repo = _enter_repo(args)
    issues = core_doctor.diagnose(git, repo)
    auto = [i for i in issues if i.fix is not None]
    do_fix = args.fix
    if not out.json_mode:
        for i in issues:
            out.warn(f"{i.kind}: {i.target}: {i.message} -> {i.action}")
        if auto and not args.dry_run and not do_fix:
            try:
                do_fix = input(f"Apply the {len(auto)} automatic fixes? [y/N] ").strip().lower() in ("y", "yes")
            except EOFError:
                do_fix = False
    result = core_doctor.report(git, repo, fix=do_fix, dry_run=args.dry_run, issues=issues)
    out.set_result(result)
    for failure in result["failures"]:
        out.warn(f"Repair failed: {failure['target']}: {failure['message']}")
    out.success(f"{len(issues)} problem(s); {result['applied']} verified fix(es); "
                f"{len(result['remaining_issues'])} remaining.")
    if not out.json_mode:
        skills = result["skills"]
        checked = ", ".join(f"{s['path']} ({s['installed_version'] or '?'})" for s in skills)
        out.plain(f"Agent Skill copies checked: {checked}" if skills else
                  "Agent Skill: no installed copy (`gwt skill install`)")
    return 0


def _worktree_target(args, git, repo):
    """Returns the target Worktree: args.target's, or the current directory's."""
    from ...core.model import list_worktrees as _lw
    if getattr(args, "target", None):
        from ...core import remove as core_remove
        return core_remove.resolve_target(git, repo, args.target)
    cwd = _base_dir(args)
    for w in _lw(git, repo, with_status=False):
        if w.is_bare or not w.branch:
            continue
        try:
            cwd.relative_to(w.path.resolve())
            return w
        except ValueError:
            continue
    raise UsageError("Specify the worktree (not detected from the current directory).")


def cmd_patch(args, out: Output) -> int:
    from ...core import patch as core_patch

    git = _make_runner(args, out)
    repo = _enter_repo(args)
    wt = _worktree_target(args, git, repo)
    base = args.base or core_config.DEFAULT_BASE

    patches_dir = None
    if core_config.ARTIFACTS_DIR:
        patches_dir = repo.root / core_config.ARTIFACTS_DIR / core_patch.PATCHES_SUBDIR

    res = core_patch.generate(
        git, repo, wt,
        base=base, wip=args.wip, fmt_patch=args.format_patch,
        patches_dir=patches_dir,
        out_path=(Path(args.output) if args.output else None),
        to_stdout=args.stdout, step=out.step,
    )

    # stdout output: the raw patch (or, in JSON, inside result).
    if args.stdout:
        if out.json_mode:
            out.set_result({"mode": res["mode"], "content": res.get("stdout", ""),
                            "empty": res["empty"]})
            out.success("patch on stdout")
        else:
            print(res.get("stdout", ""), end="")
        return 0

    out.set_result({k: v for k, v in res.items() if k != "stdout"})
    if res["empty"]:
        out.warn("The patch is empty: no differences from the base"
                 + (" (did you use --wip with no uncommitted changes?)" if args.wip else "") + ".")
    if res["mode"] == "format-patch":
        out.success(f"{len(res.get('files', []))} patch(es) in {res['path']}")
    else:
        out.success(f"Patch generated: {res['path']}")
    return 0


def cmd_artifacts(args, out: Output) -> int:
    """Prints (and creates) the path of the local artifacts folder."""
    from ...core import naming
    repo = _enter_repo(args)
    if not core_config.ARTIFACTS_DIR:
        raise UsageError("The artifacts folder is disabled (artifacts_dir empty).")

    path = repo.root / core_config.ARTIFACTS_DIR
    if args.target:
        # Subfolder: if the arg is a worktree, use its path; otherwise a slug of the arg.
        sub = None
        try:
            from ...core import remove as core_remove
            wt = core_remove.resolve_target(GitRunner(), repo, args.target)
            sub = wt.rel_path.replace("/", "-")
        except WtError:
            sub = naming.slugify(args.target)
        path = path / sub

    path.mkdir(parents=True, exist_ok=True)
    out.set_result({"path": str(path)})
    if out.json_mode:
        out.success(f"artifacts: {path}")
    else:
        print(str(path))   # bare path, for cd "$(gwt artifacts)"
    return 0


def register_doctor(sub) -> None:
    dp = sub.add_parser("doctor", help="detect and fix hygiene problems")
    _common(dp)
    dp.add_argument("--fix", action="store_true", help="apply the fixes without asking")
    dp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="report only, do not modify")
    dp.set_defaults(func=cmd_doctor)


def register_patch(sub) -> None:
    pat = sub.add_parser("patch", help="generate a patch of the worktree (diff vs base or format-patch)")
    _common(pat)
    pat.add_argument("target", nargs="?", help="worktree (default: the current one)")
    pat.add_argument("--base", help="comparison base (default: repo base branch)")
    pat.add_argument("--format-patch", dest="format_patch", action="store_true",
                     help="one .patch per commit (applyable with git am)")
    pat.add_argument("--wip", action="store_true",
                     help="include uncommitted changes (working tree vs HEAD)")
    pat.add_argument("--output", "-o", help="output path (file for diff, folder for format-patch)")
    pat.add_argument("--stdout", action="store_true",
                     help="print the patch to stdout instead of writing a file")
    pat.set_defaults(func=cmd_patch)


def register_artifacts(sub) -> None:
    ap = sub.add_parser("artifacts", help="path of the local artifacts folder (creates it if missing)")
    _common(ap)
    ap.add_argument("target", nargs="?", help="worktree or name for a subfolder (optional)")
    ap.set_defaults(func=cmd_artifacts)
