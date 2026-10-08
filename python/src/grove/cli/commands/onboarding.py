"""First-use readiness facade."""
from ...core import onboarding
from .._shared import _common


def cmd_onboard(args, out):
    result = onboarding.report(channel=args.channel, client=args.client, target=args.target,
        path=args.path, install_skill=args.install_skill, dry_run=args.dry_run,
        check_update=args.check_update, ssh=args.ssh, signing=args.signing, cwd=args.C)
    out.set_result(result)
    for check in result["checks"]:
        out.plain(f"{check['name']}: {check['status']} — {check['message']}")
    for step in result["next_steps"]:
        out.plain(step)
    out.success(f"Onboarding: {result['verdict']}")
    return 0


def register_onboard(sub):
    parser = sub.add_parser("onboard", help="inspect CLI/skill readiness and guide optional MCP setup")
    _common(parser)
    parser.add_argument("--channel", choices=["cli", "mcp"], default="cli")
    parser.add_argument("--client", default="agents", help="agents, codex, claude-code, claude-desktop or cursor")
    parser.add_argument("--target", choices=["agents", "claude", "project"], default="agents")
    parser.add_argument("--path", help="selected skill root, overrides target")
    parser.add_argument("--install-skill", action="store_true", help="install using the existing installer; preserve edits")
    parser.add_argument("--dry-run", action="store_true", help="preview installation; no writes or network")
    parser.add_argument("--check-update", action="store_true", help="optional bounded PyPI check")
    parser.add_argument("--ssh", action="store_true", help="optional read-only SSH diagnosis")
    parser.add_argument("--signing", action="store_true", help="optional passive signing diagnosis in -C worktree")
    parser.set_defaults(func=cmd_onboard)
