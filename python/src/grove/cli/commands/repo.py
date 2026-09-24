"""Repo-level commands: setup, convert (adopt), config."""

from __future__ import annotations

import sys
from pathlib import Path

from ...core import config as core_config
from ...core import setup as core_setup
from ...core.errors import UsageError
from ..output import Output
from .._shared import _base_dir, _common, _enter_repo, _make_runner, _origin_of


def _resolve_setup_url(args, out: Output) -> str:
    """Decides the final clone URL, choosing a local SSH alias if applicable."""
    from ...core import sshalias

    url = args.url
    host = sshalias.url_host(url)
    if not host:
        return url  # not SSH (e.g. https): no alias

    matches = sshalias.matching_aliases(host, out.git_echo)

    # 1) Explicit flag.
    if getattr(args, "ssh_alias", None):
        chosen = args.ssh_alias
        if chosen.lower() in ("none", "-"):
            return url
        known = {m.alias for m in matches}
        if chosen not in known and chosen not in sshalias.list_config_hosts():
            out.warn(f"Alias '{chosen}' is not in ~/.ssh/config; using it anyway.")
        new = sshalias.rewrite_host(url, chosen)
        core_config.SSH_ALIAS = chosen
        out.step(f"Using SSH alias '{chosen}' → {new}")
        return new

    if not matches:
        return url

    # 2) Interactive: ask.
    if sys.stdin.isatty() and not out.json_mode:
        out.plain(f"SSH aliases detected for {host}:")
        for i, m in enumerate(matches, 1):
            keys = ", ".join(m.identity_files) or "(no IdentityFile)"
            out.plain(f"  {i}) {m.alias}   {keys}")
        out.plain("  0) use the URL as-is (no alias)")
        try:
            ans = input("Which one to use? [0] ").strip()
        except EOFError:
            ans = ""
        if ans.isdigit() and 1 <= int(ans) <= len(matches):
            chosen = matches[int(ans) - 1].alias
            new = sshalias.rewrite_host(url, chosen)
            core_config.SSH_ALIAS = chosen
            out.step(f"Using SSH alias '{chosen}' → {new}")
            return new
        return url

    # 3) Non-interactive without flag: use as-is, but warn.
    nombres = ", ".join(m.alias for m in matches)
    out.step(f"Notice: there are SSH aliases for {host} ({nombres}). Using the URL as-is; "
             f"use --ssh-alias <alias> to choose.")
    return url


def cmd_setup(args, out: Output) -> int:
    git = _make_runner(args, out)
    into = Path(args.into).resolve() if args.into else _base_dir(args)

    # Resolve and apply the profile policy (if specified) before creating.
    profile_name = args.profile or core_config.DEFAULT_PROFILE
    try:
        policy = core_config.resolve_profile(profile_name)
    except KeyError:
        raise UsageError(f"Unknown profile: '{profile_name}'.")
    core_config.apply_policy(policy)
    out.step(f"Profile: {profile_name} (base {core_config.DEFAULT_BASE}, tickets {core_config.TICKETS})")

    url = _resolve_setup_url(args, out)

    base_branch = getattr(args, "base", None) or core_config.DEFAULT_BASE
    ctx = core_setup.setup(
        git,
        url,
        into=into,
        name=args.name,
        base_branch=base_branch,
        git_pointer=getattr(args, "git_pointer", True),
        keep_on_error=getattr(args, "keep_on_error", False),
        step=out.step,
    )
    # setup may have auto-detected a different base (e.g. 'production'); record it
    # so the written config and messages reflect the real base.
    if ctx.base:
        core_config.DEFAULT_BASE = ctx.base
    cfg_path = core_config.write_repo_config(ctx.bare, core_config.effective_policy())
    from ...core import worktree_paths as wp
    if wp.apply_if_configured(git, ctx, warn=out.warn):
        out.step("Worktrees use relative paths (relative_worktrees = true)")
    out.set_result({"name": ctx.name, "root": str(ctx.root), "profile": profile_name,
                    "base": core_config.DEFAULT_BASE})
    out.success(f"Repo {ctx.name} ready")
    if not out.quiet:
        out.plain(f"  .bare/       bare repository (+ {cfg_path.name})")
        out.plain(f"  {core_config.DEFAULT_BASE}/  [tracks origin/{core_config.DEFAULT_BASE}]")
    return 0


def cmd_convert(args, out: Output) -> int:
    from ...core import convert as core_convert

    git = _make_runner(args, out)
    path = Path(args.path).resolve() if args.path else _base_dir(args)
    ctx = core_convert.convert(
        git,
        path=path,
        into=(Path(args.into).resolve() if args.into else None),
        branches=args.branches,
        fetch=getattr(args, "fetch", True),
        force=args.force,
        git_pointer=getattr(args, "git_pointer", True),
        keep_on_error=getattr(args, "keep_on_error", False),
        dry_run=getattr(args, "dry_run", False),
        profile=getattr(args, "profile", None),
        step=out.step,
    )
    out.set_result({"name": ctx.name, "root": str(ctx.root), "base": ctx.base,
                    "profile": getattr(args, "profile", None) or core_config.DEFAULT_PROFILE,
                    "into": bool(args.into), "dry_run": getattr(args, "dry_run", False)})
    suffix = " (dry-run)" if getattr(args, "dry_run", False) else ""
    out.success(f"Converted{suffix}: {ctx.root} (base {ctx.base})")
    return 0


def cmd_config(args, out: Output) -> int:
    repo = _enter_repo(args)
    origin = _origin_of(repo)

    if args.config_command == "set-ssh-alias":
        from ...core import sshalias, sshcheck
        git = _make_runner(args, out)
        value = args.value
        if value.lower() in ("none", "-", ""):
            host = sshalias.url_host(origin) if origin else None
            new_url = origin
            if host:
                cfg, err = sshcheck._ssh_g(host)
                real = cfg.get("hostname") if not err else None
                if real:
                    new_url = sshalias.rewrite_host(origin, real)
            core_config.SSH_ALIAS = ""
        else:
            if origin is None:
                raise UsageError("There is no origin in this repo.")
            new_url = sshalias.rewrite_host(origin, value)
            core_config.SSH_ALIAS = value

        if origin and new_url != origin:
            out.step(f"Rewriting origin → {new_url}")
            git.run(["remote", "set-url", "origin", new_url], cwd=repo.bare)
        core_config.write_repo_config(repo.bare, core_config.effective_policy())
        out.set_result({"ssh_alias": core_config.SSH_ALIAS, "origin": new_url})
        out.success(f"ssh_alias = '{core_config.SSH_ALIAS or '(none)'}' · origin = {new_url}")
        return 0

    if args.config_command == "set" and args.key == "relative_worktrees":
        from ...core import worktree_paths as wp
        value = core_config._coerce(args.key, args.value)
        action = wp.set_relative(_make_runner(args, out), repo, value)
        data = core_config.read_repo_config(repo.bare)
        out.set_result({"key": args.key, "value": value, "applied": action, "config": data})
        done = {"enable": "worktrees converted to relative paths",
                "disable": "worktrees converted back to absolute paths"}.get(action, "nothing to convert")
        out.success(f"config set · relative_worktrees = {str(value).lower()} ({done})")
        return 0

    if args.config_command == "set":
        data = core_config.set_repo_value(repo.bare, args.key, args.value)
        out.set_result({"key": args.key, "value": data.get(args.key), "config": data})
        out.success(f"config set · {args.key} = {data.get(args.key)}")
        return 0

    if args.config_command == "unset":
        data = core_config.unset_repo_value(repo.bare, args.key)
        out.set_result({"unset": args.key, "config": data})
        out.success(f"config unset · {args.key}")
        return 0

    if args.config_command == "edit":
        import os
        import subprocess
        cfg_path = repo.bare / core_config.CONFIG_FILENAME
        if not cfg_path.exists():
            core_config.write_repo_config(repo.bare, core_config.effective_policy())
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        try:
            subprocess.run([*editor.split(), str(cfg_path)], check=False)
        except OSError as exc:
            raise UsageError(f"could not launch editor '{editor}': {exc}")
        out.set_result({"edited": str(cfg_path)})
        out.success(f"edited {cfg_path}")
        return 0

    # show
    from ... import __version__
    pol = core_config.effective_policy()
    report = {"repo": repo.name, "root": str(repo.root), "origin": origin,
              "version": __version__, **pol}
    out.set_result(report)
    if not out.json_mode:
        out.plain(f"Repo: {repo.name}")
        out.plain(f"  origin: {origin or '—'}")
        for k in ("default_base", "tickets", "ssh_alias", "integration_branch"):
            out.plain(f"  {k}: {pol.get(k)}")
        out.plain(f"  allowed_types: {', '.join(pol.get('allowed_types', []))}")
        out.plain(f"  special_worktrees: {', '.join(pol.get('special_worktrees', []))}")
        out.plain("  (use --json for the full detail)")
    else:
        out.success(f"Config for {repo.name}")
    return 0


def register_setup(sub) -> None:
    sp = sub.add_parser("setup", help="initialize a repo (bare + base worktree)")
    _common(sp)
    sp.add_argument("url", help="origin URL")
    sp.add_argument("--name", help="repo folder name")
    sp.add_argument("--into", help="where to create the repo folder (default: cwd)")
    sp.add_argument("--base", help="base branch (default: profile's, or autodetected from origin)")
    sp.add_argument("--no-git-pointer", dest="git_pointer", action="store_false",
                    help="don't write the root .git pointer (gitdir: ./.bare)")
    sp.add_argument("--keep-on-error", dest="keep_on_error", action="store_true",
                    help="on failure, keep the partial folder (default: clean it up)")
    sp.add_argument("--profile", help="policy profile to apply (default: default)")
    sp.add_argument("--ssh-alias", dest="ssh_alias", metavar="ALIAS",
                    help="~/.ssh/config alias to use for the remote (or 'none' for the URL as-is)")
    sp.set_defaults(func=cmd_setup)


def register_convert(sub) -> None:
    cv = sub.add_parser("convert", aliases=["adopt"],
                        help="adopt an existing clone: convert it into the grove model "
                             "without re-cloning ('adopt' is an alias)")
    _common(cv)
    cv.add_argument("path", nargs="?", help="path of the existing clone (default: cwd)")
    cv.add_argument("--into", help="create a new grove repo here; leave the source intact")
    cv.add_argument("--profile", help="policy profile to apply and record in grove.toml (default: default)")
    cv.add_argument("--branches", choices=["current", "current+base", "all"],
                    default="current+base", help="which worktrees to materialize")
    cv.add_argument("--no-fetch", dest="fetch", action="store_false",
                    help="don't contact origin (offline)")
    cv.add_argument("--force", action="store_true",
                    help="proceed even if submodules or Git LFS are detected")
    cv.add_argument("--no-git-pointer", dest="git_pointer", action="store_false",
                    help="don't write the root .git pointer (gitdir: ./.bare)")
    cv.add_argument("--keep-on-error", dest="keep_on_error", action="store_true",
                    help="on failure, keep partial output (default: clean it up; in-place stops and reports)")
    cv.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="print the plan without making changes")
    cv.set_defaults(func=cmd_convert)


def register_config(sub) -> None:
    cfgp = sub.add_parser("config", help="show or adjust the repo configuration")
    cfgp.set_defaults(func=cmd_config, config_command="show")
    cfg_sub = cfgp.add_subparsers(dest="config_command")
    cshow = cfg_sub.add_parser("show", help="report the repo configuration")
    _common(cshow)
    cshow.set_defaults(func=cmd_config, config_command="show")
    cset = cfg_sub.add_parser("set-ssh-alias", help="set the SSH alias and rewrite the origin")
    _common(cset)
    cset.add_argument("value", help="~/.ssh/config alias (or 'none' for the canonical URL)")
    cset.set_defaults(func=cmd_config, config_command="set-ssh-alias")
    cput = cfg_sub.add_parser("set", help="set a repo config key in grove.toml")
    _common(cput)
    cput.add_argument("key", help="config key (e.g. default_base, tickets, allowed_types)")
    cput.add_argument("value", help="value; comma-separated for list keys")
    cput.set_defaults(func=cmd_config, config_command="set")
    cdel = cfg_sub.add_parser("unset", help="remove a repo config key from grove.toml")
    _common(cdel)
    cdel.add_argument("key", help="config key to remove")
    cdel.set_defaults(func=cmd_config, config_command="unset")
    cedit = cfg_sub.add_parser("edit", help="open grove.toml in $EDITOR")
    _common(cedit)
    cedit.set_defaults(func=cmd_config, config_command="edit")
    # 'gwt config' without a subcommand = show
    _common(cfgp)
