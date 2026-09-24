"""`gwt repos`: list the grove-managed repos found on this machine."""

from __future__ import annotations

from ...core import repos as core_repos
from ..output import Output
from .._shared import _common


def cmd_repos(args, out: Output) -> int:
    res = core_repos.discover(args.paths or None, depth=args.depth)
    out.set_result(res)
    if not res["repos"]:
        out.warn(res["hint"] or "no grove-managed repo found")
        return 0
    width = max(len(r["path"]) for r in res["repos"])
    for r in res["repos"]:
        extra = "  ".join(x for x in (r["base"] and f"base {r['base']}", r["origin"]) if x)
        out.plain(f"  {r['path']:<{width}}  {extra}")
    return 0


def register_repos(sub) -> None:
    p = sub.add_parser(
        "repos",
        help="list grove-managed repos under the given folders (default: your identity zones)")
    _common(p)
    p.add_argument("paths", nargs="*", metavar="PATH",
                   help="folders to search (default: the zones set up with 'gwt ssh add')")
    p.add_argument("--depth", type=int, default=core_repos.DEFAULT_DEPTH,
                   help=f"how deep to look under each folder (default {core_repos.DEFAULT_DEPTH})")
    p.set_defaults(func=cmd_repos)
