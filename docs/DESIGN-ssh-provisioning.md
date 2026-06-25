# Implementation design — SSH account provisioning

> Companion to **spec §14**. The spec defines *what* the `gwt ssh add | accounts | doctor | remove`
> commands do; this document defines *how* they are built inside the Python implementation,
> aligned with grove's existing conventions (stdlib-only core, thin CLI facade, `Echo`
> callbacks, `WtError` exit codes, `Output` rendering).
>
> Status: design for review. Target: `python/src/grove/`. Mirrors the core+facade split so the
> MCP layer (§14.9) reuses the same core.

## 0. Principles carried from the existing code

- **Core is pure, offline, deterministic.** Only local subprocesses (`ssh-keygen`, `ssh-add`,
  `git config`, `ssh -G`). No network. Public-key upload is out of scope (printed for the user/agent).
- **Stdlib only.** No new pip dependencies in the base package (consistent with §11).
- **Thin CLI.** `cmd_ssh_*` functions parse args → call core ops → render via `Output`. All logic in `core`.
- **Idempotent, marker-scoped edits.** Never modify text outside grove's sentinel markers.
- **Paths are resolved per call, not at import.** Unlike `sshcheck.SSH_CONFIG` (a module constant),
  the new modules read paths through `platform.paths()` so tests can redirect `HOME`/`USERPROFILE`
  and Windows is handled. (We also refactor `sshcheck` lazily; see §9.)

## 1. Module layout

```
python/src/grove/core/
├── sshcheck.py        # EXISTING — read-only diagnostics (reused)
├── sshalias.py        # EXISTING — URL parse / host rewrite (reused)
├── platform.py        # NEW — OS layer: paths, perms, agent, keychain support
├── blockedit.py       # NEW — generic marker-scoped, idempotent, atomic text edits
├── gitidentity.py     # NEW — ~/.gitconfig hardening + includeIf/zone identity files
├── sshprov.py         # NEW — account/zone model + add/list/remove orchestration
└── sshdoctor.py       # NEW — diagnose()/apply_fixes() check registry

python/src/grove/cli/
└── main.py            # EXTEND — add subparsers + cmd_ssh_add / _accounts / _doctor / _remove

python/src/grove/mcp/
└── _ops.py            # EXTEND (phase 4) — grove_ssh_add/_accounts/_doctor/_remove

python/tests/
├── test_blockedit.py  # NEW
├── test_platform.py   # NEW
├── test_sshprov.py    # NEW (model derive + add/remove with redirected HOME)
└── test_sshdoctor.py  # NEW
```

Dependency direction (no cycles): `sshprov`/`sshdoctor` → `gitidentity`, `blockedit`, `platform`, `sshcheck`, `sshalias`.

## 2. `platform.py` — the OS layer

All OS-specific behavior is isolated here; everything else is shared. Branches on `sys.platform`.

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Paths:
    home: Path
    ssh_dir: Path        # <home>/.ssh
    ssh_config: Path     # <home>/.ssh/config
    gitconfig: Path      # <home>/.gitconfig
    identities_dir: Path # <home>/.config/grove/identities
    backups_dir: Path    # <home>/.config/grove/backups

def paths() -> Paths:
    """Resolve per call from $HOME / %USERPROFILE% (test- and Windows-friendly)."""

def is_windows() -> bool: ...
def keychain_supported() -> bool:        # True only on darwin
    ...

def enforce_key_perms(path: Path) -> bool | None:
    """chmod 600 on POSIX; returns True/False. None (N/A) on Windows."""

def check_key_perms(path: Path) -> bool | None:
    """600-ish check (no group/other bits); None on Windows (NTFS ACLs)."""

def agent_add(key: Path, echo=None) -> bool:
    """ssh-add (+ --apple-use-keychain on darwin). False if agent unreachable."""

def agent_running() -> bool: ...

def ssh_defaults_block() -> str:
    """The `Host *` defaults; includes `UseKeychain yes` only on darwin."""

def normalize_gitdir(scope_dir: Path) -> str:
    """Absolute, forward-slashed, trailing '/' — the form git's `gitdir:` expects on all OS."""
```

Windows notes captured here: `paths()` uses `%USERPROFILE%`; `enforce/check_key_perms` return `None`;
`agent_add` targets the OpenSSH Authentication Agent service and `agent_running()` warns if it is not
up; `ssh_defaults_block()` omits `UseKeychain`. Git Bash/WSL fall through to the POSIX branch.

## 3. `blockedit.py` — safe, idempotent, marker-scoped edits

The riskiest part: editing user-owned dotfiles without corrupting hand-written content. One small,
heavily-tested module, used for both `~/.ssh/config` and `~/.gitconfig` (both use `#` comments).

Marker format (kind ∈ {`account`, `zone`}):

```
# >>> grove:account=dropi-gh >>>
<body>
# <<< grove:account=dropi-gh <<<
```

API (pure string functions + thin file helpers):

```python
MARKER_RE = re.compile(r"^# (>>>|<<<) grove:(?P<kind>\w+)=(?P<id>[\w.-]+) (>>>|<<<)\s*$")

def upsert_block(text: str, kind: str, id: str, body: str) -> str:
    """Replace the existing marked region in place, or append a new one. Idempotent."""

def remove_block(text: str, kind: str, id: str) -> tuple[str, bool]:
    """Drop a marked region; (new_text, removed?)."""

def find_blocks(text: str, kind: str | None = None) -> dict[str, str]:
    """{id: body} for every grove-managed region (optionally filtered by kind)."""

# File helpers
def read_text(path: Path) -> str:                  # "" if missing
def write_atomic(path: Path, text: str) -> None:   # tmp + os.replace; mkdir parents; chmod 600 (POSIX)
def backup_once(path: Path, paths) -> None:        # timestamped copy into backups_dir, first edit only
```

Safety guarantees:

- **In place:** `upsert_block` preserves everything before/after the markers byte-for-byte; only the
  region between a marker pair changes. Appends with a single blank-line separator if creating.
- **Atomic:** write to `path + ".tmp"`, `os.replace` (same filesystem) → no half-written config.
- **Backups:** `backup_once` snapshots the original into `~/.config/grove/backups/<file>.<ts>` before
  the first modification of a run, so any edit is recoverable.
- **Never touches unmarked text:** hand-written `Host`/sections are read by higher layers but never
  passed to `remove_block`/`upsert_block`.
- **Malformed markers** (unbalanced open/close) → raise `ValidationError` (refuse to edit rather than guess).

## 4. `gitidentity.py` — git identity layer (zones + global hardening)

Mix of two mechanisms by design:

- **Plain global scalars** (`user.name`, `user.useConfigOnly`) via `git config --global` (gitrunner),
  not text parsing — git owns its own scalars.
- **Structured regions** (`includeIf` + the zone identity file) via `blockedit` markers, because
  `includeIf` is conditional and we need `remove` + idempotency with our markers.

```python
def harden_global(name: str | None, echo=None) -> list[str]:
    """Ensure user.name set (from `name` or existing) and user.useConfigOnly=true.
    Returns the list of changes applied (for the step log)."""

def conflicting_url_rewrites(echo=None) -> list[tuple[str, str]]:
    """`git config --global --get-regexp '^url\\.'` → [(key, value)] for review (e.g. token rewrites).
    Reported, NEVER auto-removed (may hold a secret)."""

def upsert_zone(scope_dir: Path, email: str, rewrites: dict[str, str], paths) -> Path:
    """Create/update: (1) the marked includeIf in ~/.gitconfig pointing to the zone identity file,
    (2) the grove-owned identity file (email + url.insteadOf per account). Returns identity path.
    `rewrites` = {real_host: alias}. Idempotent; adds an account to an existing zone."""

def zone_id_for(scope_dir: Path) -> str:
    """Stable id from the folder (e.g. '~/dropi/' -> 'dropi'); used as the marker id and file name."""

def read_zone(scope_dir: Path, paths) -> Zone | None:
    """Parse the includeIf + identity file back into a Zone (for accounts/doctor/remove)."""

def remove_account_from_zone(scope_dir, alias, paths) -> bool:
    """Drop one account's insteadOf; if the zone becomes empty, remove includeIf + identity file."""
```

The identity file is fully grove-owned (safe to rewrite wholesale); the `includeIf` block in
`~/.gitconfig` is the only thing we touch there, and only inside its marker.

## 5. `sshprov.py` — model + add/list/remove

### 5.1 Dataclasses

```python
@dataclass
class Account:
    name: str          # == Host alias
    host: str          # HostName
    key: str           # IdentityFile (expanded)
    managed: bool      # inside grove markers?

@dataclass
class Zone:
    scope_dir: str
    email: str
    identity_path: str
    rewrites: dict[str, str]   # host -> alias

@dataclass
class Inventory:
    accounts: list[Account]
    zones: list[Zone]
    def zone_of(self, account: Account) -> Zone | None: ...

@dataclass
class AddSpec:
    name: str
    host: str
    email: str | None
    scope_dir: Path | None
    key: Path | None
    no_identity: bool = False
    no_agent: bool = False
    no_passphrase: bool = False
    dry_run: bool = False
```

### 5.2 Reading (derive, no parallel state)

```python
def read_inventory(paths=None, echo=None) -> Inventory:
    # accounts: blockedit.find_blocks(ssh_config, "account") -> parse Host/HostName/IdentityFile
    # zones:    blockedit.find_blocks(gitconfig, "zone")     -> gitidentity.read_zone(...)
```

Parsing a Host body is trivial line scanning (`HostName`, `IdentityFile`, `User`); we do NOT need
`ssh -G` for the managed inventory (markers already scope it). `ssh -G` is used by `doctor` for the
*effective* resolution and conflict detection.

### 5.3 `add_account`

```python
def add_account(spec: AddSpec, paths=None, echo=None) -> dict:
    1. validate(spec.name is a valid Host token; host non-empty; if identity → email required)
    2. key = spec.key or paths.ssh_dir / f"id_ed25519_{slug(spec.name)}"
    3. keygen_if_missing(key, comment=spec.name, no_passphrase=spec.no_passphrase, dry_run)
    4. ssh_config edit (blockedit.upsert_block "account", body = Host block + IdentitiesOnly yes)
       - ensure the `Host *` defaults block exists (platform.ssh_defaults_block) — also marker-scoped
    5. if not no_identity and scope_dir:
         gitidentity.harden_global(name=...)            # useConfigOnly + user.name
         gitidentity.upsert_zone(scope_dir, email, {host: name})
    6. if not no_agent: platform.agent_add(key)
    7. pubkey = read(key + ".pub"); return {account, key, pubkey, zone, steps}
```

`keygen_if_missing`: `ssh-keygen -t ed25519 -C <name> -f <key>`. Passphrase handling is the one place
we must **not** capture stdio: when interactive and `--no-passphrase` is absent, run with inherited
stdin/stdout so the user types the passphrase; otherwise pass `-N ""`. In `--json`/MCP mode,
`--no-passphrase` (or a pre-supplied passphrase via env) is required since there is no TTY.

### 5.4 `remove_account`

```python
def remove_account(name, *, delete_key, keep_routing, dry_run, paths=None, echo=None) -> dict:
    - blockedit.remove_block(ssh_config, "account", name)
    - find the account's zone; gitidentity.remove_account_from_zone(...) unless keep_routing
    - if delete_key: unlink key + key.pub (local only; never touches the remote)
```

## 6. `sshdoctor.py` — diagnose & repair

A registry of checks; each yields `Finding`s. Mirrors worktree `doctor` semantics (§6.7): default =
report + confirm; `--fix` = apply auto-fixes; report-only items never auto-touched.

```python
@dataclass
class Finding:
    check: str           # 'perms' | 'identitiesonly' | 'agent' | 'useconfigonly' |
                         # 'username' | 'insteadof' | 'trap' | 'secret' | 'email' |
                         # 'orphan' | 'unmanaged'
    severity: str        # 'fix' (auto) | 'review' (manual)
    target: str
    message: str
    fixer: Callable[[], None] | None   # present iff severity == 'fix'

def diagnose(paths=None, echo=None) -> list[Finding]: ...
def apply_fixes(findings, echo=None) -> int:          # runs fixers; returns count applied
```

Check sources (each a small function `_check_*(inv, paths, echo) -> Iterable[Finding]`):

| check | severity | detection | fixer |
|---|---|---|---|
| `perms` | fix | `platform.check_key_perms(key) is False` | `enforce_key_perms` |
| `identitiesonly` | fix | managed Host block missing `IdentitiesOnly yes` | re-upsert block with it |
| `agent` | fix | key fingerprint not in `ssh-add -l` | `platform.agent_add` |
| `useconfigonly` | fix | `git config --global user.useConfigOnly` ≠ true | set true |
| `username` | fix | global `user.name` empty | set (asks in CLI) |
| `insteadof` | fix | a zone account lacks its `url.<alias>.insteadOf` | re-add via `upsert_zone` |
| `trap` | review | key exists only under an alias while a managed `host` resolves through `Host *` with no `IdentityFile` (`ssh -G <host>` shows default-only identities) | — |
| `secret` | review | `conflicting_url_rewrites()` value contains `:<token>@` | — |
| `email` | review | two accounts share a zone with divergent emails | — |
| `orphan` | review | marked block whose key/identity file is gone, or `includeIf` to a missing `scope_dir` | — |
| `unmanaged` | review | hand-written `Host` overlaps a managed alias/host | — |

`trap` reuses `sshcheck._ssh_g`/`check_host` and `sshalias.matching_aliases` to compare what the real
host resolves to vs. where the key lives — the exact bug from the guide.

## 7. CLI wiring (`cli/main.py`)

Extend the existing `ssh` subparser group:

```python
ssh_sub = ssp.add_subparsers(dest="ssh_command")
# ... existing 'check' ...

add = ssh_sub.add_parser("add", help="provision an SSH account (key + config + git routing)")
_common(add)
add.add_argument("name")
add.add_argument("--host", required=True)
add.add_argument("--email")
add.add_argument("--scope-dir", dest="scope_dir")
add.add_argument("--key")
add.add_argument("--no-identity", action="store_true")
add.add_argument("--no-agent", action="store_true")
add.add_argument("--no-passphrase", action="store_true")
add.add_argument("--print-pubkey", action="store_true")
add.add_argument("--dry-run", action="store_true")
add.set_defaults(func=cmd_ssh_add)

acc = ssh_sub.add_parser("accounts", help="list grove-managed SSH accounts")
_common(acc); acc.set_defaults(func=cmd_ssh_accounts)

doc = ssh_sub.add_parser("doctor", help="diagnose & repair the SSH/git multi-account setup")
_common(doc)
doc.add_argument("--fix", action="store_true")
doc.add_argument("--dry-run", action="store_true")
doc.set_defaults(func=cmd_ssh_doctor)

rm = ssh_sub.add_parser("remove", help="remove a grove-managed SSH account")
_common(rm)
rm.add_argument("name")
rm.add_argument("--delete-key", action="store_true")
rm.add_argument("--keep-routing", action="store_true")
rm.add_argument("--dry-run", action="store_true")
rm.set_defaults(func=cmd_ssh_remove)
```

`cmd_ssh_*` are thin (≈ the size of `cmd_ssh_check`): build the spec from `args`, call the core op with
`echo=out.git_echo`, emit `out.step/success/warn`, set `out.set_result(...)` for `--json`, raise
`ValidationError`/`UsageError` on bad input. `cmd_ssh_doctor` reuses the worktree-doctor confirmation
pattern: without `--fix`, print the plan and ask `[y/N]` (skipped in `--json`, which requires `--fix`).

These commands **do not require a managed repo** (like `ssh check`): they operate on `~`.

## 8. Output / JSON / exit codes

- Human: `→` steps, `✓` success, `!` review items, `✗` errors (existing `Output`).
- `--json`: `set_result(...)` with `accounts`, `findings`, or the add summary; the envelope is emitted by
  `main()` exactly as today.
- Exit codes (existing map): `0` ok; `1` validation (`ValidationError`); `2` git/ssh subprocess
  (`GitError`); `3` usage (`UsageError`). `doctor` returns `0` if nothing pending, `1` if review items
  remain after fixes (so CI can gate).

## 9. Reuse & a small refactor of `sshcheck`

- Reuse `sshcheck._ssh_g`, `check_host`, `_agent_fingerprints`, `_fingerprint_of`, `list_config_hosts`,
  and `sshalias.matching_aliases`/`rewrite_host` as-is.
- Refactor: `sshcheck.SSH_CONFIG`/`SSH_DIR` are import-time constants bound to `Path.home()`. Add
  `platform.paths()` and have the new modules use it; optionally thread an explicit `ssh_config`
  argument through the few `sshcheck` helpers we call so tests can redirect `HOME`. Backward compatible
  (defaults unchanged).

## 10. Testing strategy

Pure-stdlib `pytest`, no network, redirected `HOME`.

- **`test_blockedit.py`** — upsert creates/updates idempotently (run twice → identical); content before
  and after markers is byte-preserved; remove drops only its region; `find_blocks` parses; unbalanced
  markers raise; `write_atomic` leaves no `.tmp`.
- **`test_platform.py`** — `normalize_gitdir` (trailing slash, forward slashes); perms helpers guarded by
  `sys.platform` (skip on win); `keychain_supported()` only on darwin (monkeypatch `sys.platform`).
- **`test_sshprov.py`** — `read_inventory` from crafted `~/.ssh/config` + `~/.gitconfig` text →
  expected accounts/zones; `add_account(dry_run)` plans without writing; real `add_account` with
  `--no-agent --no-passphrase` into a tmp HOME writes correct marked blocks + zone file + pubkey;
  re-running is idempotent; `remove_account` cleans blocks and (optionally) the zone.
- **`test_sshdoctor.py`** — craft each broken state (bad perms, missing IdentitiesOnly, useConfigOnly
  unset, missing insteadOf, token in url rewrite, host-vs-alias trap) → assert the expected `Finding`
  and that `apply_fixes` resolves the auto-fixable ones and leaves review items.
- `ssh-keygen`/`ssh-add`/`git` are invoked for real in integration tests (present on CI runners);
  unit tests for parsing/editing avoid them entirely. A thin seam allows monkeypatching the subprocess
  runner where we want hermetic tests.

Conformance (§12): add OS-tagged black-box cases (config text in → resulting files out) so Go/Rust stay
in parity; the marker format and zone-file layout are part of the contract.

## 11. Build phases (incremental, each shippable)

1. **`platform` + `blockedit`** with full unit tests (no commands yet). Foundation, lowest risk.
2. **`sshprov.read_inventory` + `cmd_ssh_accounts`** — read-only; immediate value, exercises the model.
3. **`gitidentity` + `sshprov.add_account` + `cmd_ssh_add`** — the provisioning path (keygen, blocks,
   zones, agent). Gated behind `--dry-run` first.
4. **`sshdoctor` + `cmd_ssh_doctor`** — the diagnose/repair engine (the highest-value feature).
5. **`cmd_ssh_remove`** — teardown.
6. **MCP tools** (`grove_ssh_add/_accounts/_doctor/_remove`) in `mcp/_ops.py` (§14.9), reusing the core;
   `--json` result shapes are already the tool payloads.

Each phase reuses the previous; nothing is thrown away. Phases 1–2 can land before any file-mutating
code exists, keeping risk low.
