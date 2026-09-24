"""`gwt skill install`: install grove's Agent Skill for AI agents."""

from __future__ import annotations

from pathlib import Path

from ...core import skill as core_skill
from ..output import Output
from .._shared import _common


def cmd_skill_install(args, out: Output) -> int:
    if args.path:
        root = Path(args.path).expanduser()
    else:
        root = core_skill.target_root(args.target)
    res = core_skill.install(dest_root=root, force=args.force, dry_run=args.dry_run)
    out.set_result(res)
    if res["mode"] in ("edited", "unverified"):
        why = "was edited" if res["mode"] == "edited" else "has no install manifest (can't tell if it was edited)"
        out.warn(f"{res['path']} {why}; differs: {', '.join(res['differs'])}. "
                 f"A real install needs --force (dry-run)")
        return 0
    verb = {"created": "Installed", "updated": "Updated", "unchanged": "Already up to date"}[res["mode"]]
    out.success(f"{verb}: {res['path']}" + (" (dry-run)" if args.dry_run else ""))
    return 0


def cmd_skill_status(args, out: Output) -> int:
    res = core_skill.machine_status()
    out.set_result(res)
    for r in res["skills"]:
        state = ("outdated" if r["outdated"] else "current") + \
            {True: ", edited", False: "", None: ", no manifest"}[r["edited"]]
        out.plain(f"  {r['path']:<26} {r['installed_version'] or '?':<9} {state}")
    if res["hint"]:
        out.warn(res["hint"])
    else:
        out.success(f"All copies match grove {res['version']}")
    return 0


def cmd_skill_help(args, out: Output) -> int:
    out.plain("usage: gwt skill install [--claude | --project | --path DIR] [--force] [--dry-run]\n"
              "       gwt skill status")
    return 0


def register_skill(sub) -> None:
    sp = sub.add_parser("skill", help="install grove's Agent Skill (how to work with grove) for AI agents")
    sp.set_defaults(func=cmd_skill_help)
    ssub = sp.add_subparsers(dest="skill_command")
    ip = ssub.add_parser(
        "install",
        help="copy the skill to ~/.agents/skills (default), ~/.claude/skills or the project")
    _common(ip)
    tgt = ip.add_mutually_exclusive_group()
    tgt.add_argument("--claude", dest="target", action="store_const", const="claude",
                     help="install into ~/.claude/skills")
    tgt.add_argument("--project", dest="target", action="store_const", const="project",
                     help="install into the current worktree's .agents/skills")
    tgt.add_argument("--path", help="install into DIR/grove")
    ip.add_argument("--force", action="store_true",
                    help="overwrite a copy that was edited (or has no install manifest); untouched copies are refreshed anyway")
    ip.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="show what would be installed without writing")
    ip.set_defaults(func=cmd_skill_install, target="agents")
    stp = ssub.add_parser("status", help="state of the installed copies vs this grove (no repo needed)")
    _common(stp)
    stp.set_defaults(func=cmd_skill_status)
