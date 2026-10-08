"""Git identity layer: global hardening + per-folder zones (includeIf + insteadOf).

Two mechanisms by design:

* **Plain global scalars** (``user.name``, ``user.useConfigOnly``) are written with
  ``git config --global`` — git owns its own scalars.
* **Structured regions** (the ``includeIf`` block in ``~/.gitconfig`` and the
  grove-owned zone identity file) are written with marker-scoped ``blockedit``,
  because ``includeIf`` is conditional and we need idempotent upsert + removal.
"""

from __future__ import annotations

import os
import re
import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .errors import ValidationError
from . import blockedit
from . import platform as plat

_URL_KEY_RE = re.compile(r'^\[url\s+"git@(?P<alias>[\w.\-]+):"\]')
_HOST_FROM_INSTEADOF = re.compile(r'(?:git@|https://)(?P<host>[\w.\-]+)[:/]')


# --------------------------------------------------------------------------- #
# Global scalars (via git config)
# --------------------------------------------------------------------------- #

def _global_cwd():
    """A neutral directory for machine-level git commands.

    `git config --global` doesn't need a repo, but git still inspects the cwd:
    inside a folder whose `.git` is broken (a worktree seen from another mount,
    a deleted repo) it fails with "not a git repository". Running from $HOME
    avoids depending on wherever the process happens to be.
    """
    home = plat.paths().home
    return home if home.is_dir() else None


def run_global(git, args, **kw):
    """Run a `git config --global …` command from a neutral cwd."""
    return git.run(args, cwd=_global_cwd(), **kw)


def _get_global(git, key: str) -> str:
    return run_global(git, ["config", "--global", "--get", key],
                      check=False, mutating=False).stdout.strip()


def harden_global(git, name: Optional[str] = None, *, dry_run=False) -> dict:
    """Ensure `user.useConfigOnly=true` (so git can never auto-invent an identity)
    and, if missing and `name` is given, `user.name`. Returns {changes, name}."""
    changes: List[str] = []
    if _get_global(git, "user.useConfigOnly").lower() != "true":
        if not dry_run:
            run_global(git, ["config", "--global", "user.useConfigOnly", "true"])
        changes.append("user.useConfigOnly = true")
    cur_name = _get_global(git, "user.name")
    if not cur_name and name:
        if not dry_run:
            run_global(git, ["config", "--global", "user.name", name])
        cur_name = name
        changes.append(f"user.name = {name}")
    return {"changes": changes, "name": cur_name}


def conflicting_url_rewrites(git) -> List[Tuple[str, str]]:
    """Global `url.*` rewrites (for doctor to review; e.g. token-bearing ones)."""
    proc = run_global(git, ["config", "--global", "--get-regexp", r"^url\."],
                      check=False, mutating=False)
    out: List[Tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if " " in line:
            k, v = line.split(" ", 1)
            out.append((k.strip(), v.strip()))
    return out


# --------------------------------------------------------------------------- #
# Identity file (selective edits of managed values)
# --------------------------------------------------------------------------- #

def zone_id_for(scope_dir) -> str:
    """Readable slug plus a digest of the normalized absolute folder."""
    normalized = plat.normalize_gitdir(scope_dir)
    name = Path(normalized.rstrip("/")).name
    slug = re.sub(r"[^\w.\-]+", "-", name).strip("-").lower() or "zone"
    return f"{slug}-{hashlib.sha256(normalized.encode()).hexdigest()[:12]}"


def _config_run(path, args, *, allow_missing=False):
    try:
        proc = subprocess.run(["git", "config", "--file", str(path), *args],
                              capture_output=True, text=True, timeout=10,
                              stdin=subprocess.DEVNULL, cwd=Path(path).parent)
    except FileNotFoundError as exc:
        raise ValidationError("Git is unavailable; install it before inspecting identity configuration.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("Git identity inspection timed out; review the file and retry.") from exc
    if proc.returncode != 0 and not (allow_missing and proc.returncode in (1, 5)):
        raise ValidationError("Invalid Git identity configuration; review it before editing.")
    return proc.stdout


def config_items(text: str) -> list[tuple[str, str]]:
    with tempfile.TemporaryDirectory(prefix="grove-config-") as directory:
        path = Path(directory) / "config"
        path.write_text(text, encoding="utf-8")
        result = _config_run(path, ["--null", "--list", "--no-includes"])
    return [tuple(item.split("\n", 1)) if "\n" in item else (item, "")
            for item in result.split("\0") if item]


def zone_reference(body: str, gitconfig: Path) -> tuple[str, Path]:
    items = config_items(body)
    includes = [(key, value) for key, value in items
                if key.lower().startswith("includeif.gitdir:") and key.lower().endswith(".path")]
    if len(includes) != 1 or len(items) != 1:
        raise ValidationError("Ambiguous Grove zone include; review the marked block before editing.")
    key, value = includes[0]
    scope = plat.normalize_gitdir(key[len("includeif.gitdir:"):-len(".path")])
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = gitconfig.parent / path
    return scope, path.absolute()


def _zone_location(scope_dir, paths):
    scope = plat.normalize_gitdir(scope_dir)
    matches = []
    refs = []
    for zid, body in blockedit.find_blocks(blockedit.read_text(paths.gitconfig), "zone").items():
        folder, identity = zone_reference(body, paths.gitconfig)
        refs.append((folder, identity))
        if folder == scope:
            matches.append((zid, identity))
    if len({folder for folder, _ in refs}) != len(refs) or len({p.resolve() for _, p in refs}) != len(refs):
        raise ValidationError("Ambiguous Grove zones: folders and identity files must be unique.")
    if matches:
        return matches[0]
    zid = zone_id_for(scope_dir)
    identity = paths.identities_dir / f"{zid}.gitconfig"
    if identity.exists() or identity.is_symlink():
        raise ValidationError(f"Unreferenced identity file {identity}; review it before creating a zone.")
    return zid, identity


def _edit_identity(text, email, old_rewrites, new_rewrites):
    """Let Git edit owned values, preserving unrelated settings and comments."""
    with tempfile.TemporaryDirectory(prefix="grove-identity-") as directory:
        path = Path(directory) / "config"
        path.write_text(text, encoding="utf-8")
        _config_run(path, ["--list", "--no-includes"])
        for host, alias in old_rewrites.items():
            for prefix in (f"git@{host}:", f"https://{host}/"):
                _config_run(path, ["--fixed-value", "--unset-all", f"url.git@{alias}:.insteadOf", prefix],
                            allow_missing=True)
        if email is None:
            _config_run(path, ["--unset-all", "user.email"], allow_missing=True)
        else:
            _config_run(path, ["--replace-all", "user.email", email])
        for host, alias in sorted(new_rewrites.items()):
            for prefix in (f"git@{host}:", f"https://{host}/"):
                _config_run(path, ["--add", f"url.git@{alias}:.insteadOf", prefix])
        return path.read_text(encoding="utf-8")


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def render_identity(email: str, rewrites: Dict[str, str]) -> str:
    """Text of a zone identity file: [user] email + url.insteadOf per account."""
    lines = ["# grove-owned identity file — managed by `gwt ssh`; additional settings are preserved.",
             "", "[user]", f"    email = {_quote(email)}"]
    for host, alias in sorted(rewrites.items()):
        lines += ["", f'[url "git@{alias}:"]',
                  f"    insteadOf = git@{host}:",
                  f"    insteadOf = https://{host}/"]
    return "\n".join(lines) + "\n"


def read_identity(path: Path) -> Tuple[str, Dict[str, str]]:
    items = config_items(blockedit.read_text(path))
    email = ""
    rewrites = {}
    for key, value in items:
        if key.lower() == "user.email":
            email = value
        elif key.lower().startswith("url.git@") and key.lower().endswith(":.insteadof"):
            alias = key[len("url.git@"): -len(":.insteadof")]
            host = _HOST_FROM_INSTEADOF.fullmatch(value)
            if host:
                real_host = host.group("host")
                if real_host in rewrites and rewrites[real_host] != alias:
                    raise ValidationError("Ambiguous host routing in the identity file; review it before editing.")
                rewrites[real_host] = alias
    return email, rewrites


# --------------------------------------------------------------------------- #
# Zone upsert / removal (includeIf + identity file)
# --------------------------------------------------------------------------- #

def upsert_zone(scope_dir, email: str, rewrites: Dict[str, str],
                paths: plat.Paths, *, dry_run: bool = False) -> Path:
    with blockedit.edit_scope():
        zid, identity_path = _zone_location(scope_dir, paths)
        original = blockedit.read_text(identity_path)
        existing_email, existing_rewrites = read_identity(identity_path)
        if email and existing_email and email != existing_email:
            raise ValidationError("The zone already has another email; review its identity before changing it.")
        if any(host in existing_rewrites and existing_rewrites[host] != alias
               for host, alias in rewrites.items()):
            raise ValidationError("The zone already routes this host to another account; review it before changing routing.")
        merged = {**existing_rewrites, **rewrites}
        final_email = email or existing_email
        content = (_edit_identity(original, final_email, existing_rewrites, merged)
                   if original else render_identity(final_email, merged))
        git_text = blockedit.read_text(paths.gitconfig)
        body = f'[includeIf {_quote("gitdir:" + plat.normalize_gitdir(scope_dir))}]\n    path = {_quote(str(identity_path))}'
        updated = blockedit.upsert_block(git_text, "zone", zid, body)
        if not dry_run:
            blockedit.backup_once(identity_path, paths.backups_dir)
            blockedit.write_atomic(identity_path, content, expected=original)
            blockedit.backup_once(paths.gitconfig, paths.backups_dir)
            blockedit.write_atomic(paths.gitconfig, updated, expected=git_text)
        return identity_path


def remove_account_from_zone(scope_dir, alias: str, paths: plat.Paths,
                             *, dry_run: bool = False) -> bool:
    with blockedit.edit_scope():
        zid, identity_path = _zone_location(scope_dir, paths)
        original = blockedit.read_text(identity_path)
        email, rewrites = read_identity(identity_path)
        remaining = {h: a for h, a in rewrites.items() if a != alias}
        content = _edit_identity(original, email if remaining else None, rewrites, remaining)
        useful = bool(config_items(content)) or any(
            line.strip().startswith(("#", ";")) and not line.startswith("# grove-owned identity file")
            for line in content.splitlines())
        if dry_run:
            return True
        blockedit.backup_once(identity_path, paths.backups_dir)
        if useful:
            blockedit.write_atomic(identity_path, content, expected=original)
        else:
            git_text = blockedit.read_text(paths.gitconfig)
            new_git, _ = blockedit.remove_block(git_text, "zone", zid)
            blockedit.backup_once(paths.gitconfig, paths.backups_dir)
            blockedit.write_atomic(paths.gitconfig, new_git, expected=git_text)
            # Recheck before deletion so external edits are never silently removed.
            with blockedit._file_lock(identity_path.resolve()):
                if blockedit.read_text(identity_path) != original:
                    raise ValidationError("Concurrent identity edit; the identity file was retained.")
                identity_path.unlink(missing_ok=True)
        return True
