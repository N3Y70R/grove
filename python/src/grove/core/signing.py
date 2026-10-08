"""Local SSH signing configuration, with plans shared by CLI and MCP."""
from __future__ import annotations

from functools import wraps
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from . import blockedit, gitidentity, platform, sshprov
from .errors import GitError, UsageError, ValidationError
from .repo import find_repo

KEYS = ("gpg.format", "user.signingkey", "commit.gpgsign", "gpg.ssh.program",
        "gpg.ssh.defaultkeycommand", "gpg.ssh.allowedsignersfile", "gpg.ssh.revocationfile",
        "user.name", "user.email")
OWNED = ("gpg.format", "user.signingkey", "commit.gpgsign")
MARKER = "ssh"


def command_echo(args, echo):
    if echo:
        from .signingdoctor import safe
        echo([safe(str(arg)) for arg in args])


def run(args, cwd, *, env=None, input=None, check=True, echo=None):
    command_echo(args, echo)
    try:
        proc = subprocess.run(args, cwd=cwd, env=env, input=input, text=True,
                              capture_output=True, timeout=15,
                              stdin=subprocess.DEVNULL if input is None else None)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise GitError("Signing inspection could not complete; check Git/OpenSSH availability and retry.") from exc
    if check and proc.returncode:
        # Never include arbitrary command output here (it can contain supplied secrets).
        raise GitError("Git could not inspect signing configuration; review its syntax and context.")
    return proc


def operation_errors(function):
    """Map filesystem/encoding failures to the same operational CLI/MCP error."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, UnicodeError) as exc:
            raise GitError("Signing operation could not access its files; review permissions/encoding and retry.") from exc
    return wrapped


def context(cwd=None, *, echo=None):
    directory = Path(cwd or Path.cwd()).resolve()
    if not directory.is_dir():
        raise UsageError("Signing context must be an existing directory.")
    repo = find_repo(directory)
    # Explicit --git-dir works even in containers lacking the optional .git pointer.
    if directory == repo.root:
        directory = repo.bare
    common = run(["git", "rev-parse", "--git-common-dir"], directory, echo=echo).stdout.strip()
    if key_path(common, directory).resolve() != repo.bare.resolve():
        raise UsageError("Git environment selects a different repository; review GIT_DIR/GIT_WORK_TREE before signing.")
    return directory, repo


def configuration(directory, *, echo=None):
    proc = run(["git", "config", "--null", "--list", "--show-origin", "--show-scope"], directory, echo=echo)
    fields = proc.stdout.split("\0")
    records = []
    for i in range(0, len(fields) - 2, 3):
        scope, origin, item = fields[i:i + 3]
        key, _, value = item.partition("\n")
        if key.lower() in KEYS:
            records.append({"key": key.lower(), "value": value, "scope": scope, "origin": origin})
    return records


def effective(records):
    return {r["key"]: r["value"] for r in records}


def key_path(value, directory):
    path = Path(os.path.expanduser(value))
    return path if path.is_absolute() else Path(directory) / path


def _selected(account, key, directory, *, echo=None):
    if bool(account) == bool(key):
        raise UsageError("Select exactly one of --account or --key.")
    inv = sshprov.read_inventory() if account else None
    chosen = None
    if account:
        matches = [a for a in inv.accounts if a.name == account]
        if len(matches) != 1:
            raise UsageError("Select an existing, unambiguous Grove SSH account.")
        chosen = matches[0]
        key = chosen.key
    path = key_path(key, directory).resolve()
    if not path.is_file():
        raise ValidationError(f"Signing key does not exist: {path}")
    if any(c in str(path) for c in "\n\r\0"):
        raise UsageError("Signing key paths cannot contain control characters.")
    probe = run(["ssh-keygen", "-l", "-f", str(path)], directory, check=False, echo=echo)
    if probe.returncode:
        raise ValidationError("The selected file is not a readable SSH signing key; review it with OpenSSH.")
    return str(path), chosen


def target(repo, scope, scope_dir=None, chosen=None):
    if scope == "repo":
        if scope_dir:
            raise UsageError("--scope-dir only applies to zone signing.")
        return repo.bare / "config"
    if scope != "zone":
        raise UsageError("Signing scope must be repo or zone.")
    folder = scope_dir or (chosen.zone_dir if chosen else None)
    if not folder:
        raise UsageError("Zone signing needs an explicit --scope-dir or an account with a zone.")
    normalized = platform.normalize_gitdir(folder)
    inv = sshprov.read_inventory()
    matches = [z for z in inv.zones if z.scope_dir == normalized]
    if len(matches) != 1:
        raise UsageError("Select an existing, unambiguous Grove identity zone.")
    # Resolve/validate duplicate folders/files and legacy references using existing logic.
    _, identity = gitidentity._zone_location(folder, platform.paths())
    if identity.resolve() != Path(matches[0].identity_path).resolve():
        raise ValidationError("Conflicting Grove zone identity references.")
    try:
        repo.bare.resolve().relative_to(Path(normalized.rstrip("/")).resolve())
    except ValueError as exc:
        raise UsageError("The selected repository must be inside the signing zone.") from exc
    return identity


def _body(values):
    payload = ("[gpg]\n\tformat = ssh\n[user]\n\tsigningKey = " + gitidentity._quote(values["user.signingkey"])
               + "\n[commit]\n\tgpgSign = true\n")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return "# grove-signing-sha256: " + digest + "\n" + payload


def owned_body(text):
    blocks = blockedit.find_blocks(text, "signing")
    if not blocks:
        return None
    if set(blocks) != {MARKER}:
        raise ValidationError("Unknown Grove signing blocks; review them before changing signing.")
    body = blocks[MARKER]
    header, sep, payload = body.partition("\n")
    digest = hashlib.sha256((payload + "\n").encode()).hexdigest()
    if not sep or header != "# grove-signing-sha256: " + digest:
        raise ValidationError("The Grove signing block was edited; review it before enable/disable.")
    items = dict(gitidentity.config_items(payload))
    if set(items) != set(OWNED) or items.get("gpg.format") != "ssh" or items.get("commit.gpgsign") != "true":
        raise ValidationError("Invalid Grove signing block; no changes performed.")
    return items


def _origin_path(origin, directory):
    if not origin.startswith("file:"):
        return None
    return key_path(origin[5:], directory).resolve()


def _preview(directory, file, updated, records, *, enabling, echo=None):
    """Resolve includes in a temporary copy; reject higher/later external overrides.

    Repository metadata is never modified to preview an edit. Git evaluates
    includeIf using the selected repository even with an explicit --file.
    """
    # Keep relative includes relative to their ORIGINAL file, not to the temp dir.
    items = gitidentity.config_items(updated)
    with tempfile.TemporaryDirectory(prefix="grove-signing-plan-") as folder:
        copy = Path(folder) / "config"
        copy.write_text(updated, encoding="utf-8")
        for k, v in items:
            if k.startswith("include") and k.endswith(".path") and not Path(os.path.expanduser(v)).is_absolute():
                gitidentity._config_run(copy, ["--fixed-value", "--replace-all", k, str(file.parent / v), v])
        proc = run(["git", "config", "--file", str(copy), "--includes", "--null", "--list"], directory, echo=echo)
    local = {}
    for item in proc.stdout.split("\0"):
        k, _, v = item.partition("\n")
        if k in OWNED:
            local[k] = v
    result = effective(records)
    scope_rank = {"system": 0, "global": 1, "local": 2, "worktree": 3, "command": 4}
    rank = 2 if file.resolve() == (find_repo(directory).bare / "config").resolve() else 1
    # The target must be present in the effective configuration (zone includes).
    target_records = [r for r in records if _origin_path(r["origin"], directory) == file.resolve()]
    for k in OWNED:
        external = [r for r in records if r["key"] == k and
                    _origin_path(r["origin"], directory) != file.resolve()]
        higher = [r for r in external if scope_rank.get(r["scope"], 4) > rank]
        if enabling and higher and k in local:
            raise ValidationError(f"{k} is overridden by {higher[-1]['origin']}; review that scope first.")
        # At the same level includes could execute after an existing block.
        same = [r for r in external if scope_rank.get(r["scope"], 4) == rank]
        if enabling and same and k in local:
            raise ValidationError(f"{k} also comes from {same[-1]['origin']}; resolve the competing include first.")
        target_index = max((i for i, r in enumerate(records) if r in target_records), default=-1)
        later_same = [r for i, r in enumerate(records) if i > target_index and r in same]
        if k in local and not higher:
            result[k] = later_same[-1]["value"] if later_same else local[k]
        else:
            remaining = [r for r in records if r["key"] == k and r not in target_records]
            if remaining:
                result[k] = remaining[-1]["value"]
            else:
                result.pop(k, None)
    return result


@operation_errors
def configure(*, enable, account=None, key=None, scope="repo", scope_dir=None, cwd=None, dry_run=False, echo=None):
    directory, repo = context(cwd, echo=echo)
    chosen = None
    selected = None
    if enable:
        selected, chosen = _selected(account, key, directory, echo=echo)
    file = target(repo, scope, scope_dir, chosen)
    original = blockedit.read_text(file)
    prior = owned_body(original)
    # Move a validated block to the end so unrelated earlier values stay untouched.
    stripped, _ = blockedit.remove_block(original, "signing", MARKER)
    updated = blockedit.upsert_block(stripped, "signing", MARKER,
                                    _body({"user.signingkey": selected})) if enable else stripped
    records = configuration(directory, echo=echo)
    if scope == "zone" and not any(_origin_path(r["origin"], directory) == file.resolve() for r in records):
        raise ValidationError("The selected identity zone is not active in this Git context; review its conditional include.")
    predicted = _preview(directory, file, updated, records, enabling=enable, echo=echo) if original != updated else effective(records)
    wanted = {"gpg.format": "ssh", "user.signingkey": selected, "commit.gpgsign": "true"}
    if enable and any(predicted.get(k) != v for k, v in wanted.items()):
        raise ValidationError("The selected signing settings would not be effective; review includes and overrides.")
    before = effective(records)
    changes = [{"file": str(file), "key": k, "before": before.get(k), "after": predicted.get(k)} for k in OWNED
               if before.get(k) != predicted.get(k)]
    changed = original != updated
    if changed and not dry_run:
        try:
            with blockedit.edit_scope():
                blockedit.backup_once(file, platform.paths().backups_dir)
                blockedit.write_atomic(file, updated, expected=original)
        except OSError as exc:
            raise GitError("Signing configuration could not be saved; review file permissions and backups.") from exc
    after_records = configuration(directory, echo=echo) if not dry_run else records
    actual = effective(after_records) if not dry_run else predicted
    if enable and not dry_run and any(actual.get(k) != v for k, v in wanted.items()):
        raise ValidationError("Configuration changed concurrently after writing; diagnose signing before committing.")
    return {"scope": scope, "file": str(file), "enabled": actual.get("commit.gpgsign", "false").lower() in ("true", "yes", "on", "1"),
            "managed": enable if changed else prior is not None,
            "changed": changed, "dry_run": dry_run, "changes": changes,
            "configuration": after_records, "effective": actual,
            "message": ("Signing plan prepared." if dry_run else
                        "SSH signing configured." if enable else "Managed signing settings removed; inherited settings may remain active.")}
