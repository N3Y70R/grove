# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/), versioned per implementation with tags `python/vX.Y.Z`, `go/vX.Y.Z`, `rust/vX.Y.Z`.

## python — unreleased

### Added

- **`create temp --base <branch>`**: temporary worktrees can now branch off a
  specific base (previously they always used the repo default). Exposed in the
  `grove_create` MCP tool via `base` for `kind="temp"`.
- **`setup` auto-detects the base branch**: if the profile/`--base` base doesn't
  exist on origin, grove falls back to the origin's default branch (e.g. repos
  whose base is `production`, not `main`) and records it in `grove.toml`. Added
  `gwt setup --base` and a `base` arg to the `grove_setup` MCP tool.
- **Docs**: MCP client guide ([docs/MCP.md](docs/MCP.md)) with conversational
  (chat) flow examples; tutorial pointer to it; `docs/FEEDBACK.md` capturing
  real-world usage findings and the improvement backlog.

## python — 0.4.0

### Added

- **SSH account provisioning** (`gwt ssh add | accounts | doctor | remove`) — a machine-level capability to set up, inventory, diagnose and tear down a multi-account SSH + git-identity configuration in an organized, repeatable and "bulletproof" way (spec §14). The folder a repo lives in decides everything: which SSH key authenticates (alias + `insteadOf` routing) and which git identity signs commits (`includeIf` + per-zone email).
  - `gwt ssh add <name> --host <h> [--email <e> --scope-dir <dir>]`: generates an ed25519 key, writes a marker-scoped `Host` block (with `IdentitiesOnly yes`), wires the zone (`includeIf` + identity file with `insteadOf`), hardens `~/.gitconfig` (`user.useConfigOnly = true`), loads the key into the agent (macOS Keychain when available) and prints the public key to upload. Idempotent; `--dry-run`, `--no-identity`, `--no-agent`, `--no-passphrase`, `--print-pubkey`.
  - `gwt ssh accounts`: inventory of grove-managed accounts/zones with routing coherence (derived from the canonical files; no parallel state).
  - `gwt ssh doctor [--fix]`: diagnose & repair — open key permissions, missing `IdentitiesOnly`/`insteadOf`, key not in agent, `useConfigOnly` unset (auto-fix); host-vs-alias trap, embedded secrets in `url.*`, orphans, missing `user.name` (report-only).
  - `gwt ssh remove <name> [--delete-key] [--keep-routing]`: removes the SSH block and its zone routing (keeps keys by default).
- **Cross-platform** support (macOS, Linux, Windows) isolated in a `core/platform` layer: home paths (`HOME`/`%USERPROFILE%`), key permissions (`600` on POSIX, N/A on Windows), agent loading (`--apple-use-keychain` only on macOS), `gitdir` normalization. New `core` modules: `platform`, `blockedit` (idempotent, atomic, marker-scoped edits of `~/.ssh/config` and `~/.gitconfig`), `gitidentity`, `sshprov`, `sshdoctor`.
- **MCP tools** for the above: `grove_ssh_add`, `grove_ssh_accounts`, `grove_ssh_doctor`, `grove_ssh_remove` (§14.9). The agent uploads the printed public key via its own hosting connector; grove stays offline.

## python — 0.3.0

### Added

- **MCP facade** (`grove.mcp`): worktree operations exposed as MCP tools over stdio for an agent to invoke — `grove_setup`, `grove_list`, `grove_create`, `grove_track`, `grove_remove`, `grove_sync`, `grove_publish`, `grove_doctor`, `grove_compare`, `grove_config`, `grove_ssh_check`. Thin facade over `core` with typed inputs, structured output and confirmation by parameter for destructive actions (no network, no ticket clients). Optional extra `pip install "grove[mcp]"` and `grove-mcp` entry point; the base CLI stays dependency-free.
- **Test suite** (`pytest`): unit tests (naming, config, compare, sshalias) and integration tests against an ephemeral local origin (setup/create/track/compare/patch), plus tests for the MCP operation layer. Optional extra `[test]` and a CI step.

### Fixed

- CI functional smoke seeded the wrong base branch (`production` vs the `default` profile's `main`); residual Spanish strings in `cli/main.py` and `core/publish.py`.

## python — 0.2.0

### Changed

- **Project language switched to English** (docs, code comments/docstrings, and all CLI output: help, messages, errors). English is now the single canonical language. The spec file was renamed `spec/especificacion.md` → `spec/specification.md`.

## python — 0.1.11

### Added

- **`gwt patch`** command: generates a patch of the worktree to share/back up without pushing — combined diff vs base (default), `--format-patch` per commit, `--wip` (uncommitted); output to `artifacts/patches/` or via `--output`/`--stdout`.

## python — 0.1.10

### Added

- **`gwt compare`** command (read-only): sync status (ahead/behind) between branches/worktrees — current worktree vs upstream, any two refs, or `--vs <ref>` against all worktrees; optional `--fetch`.

## python — 0.1.9

### Added

- Local **artifacts** folder (`artifacts/`, configurable via `artifacts_dir`): a flat folder outside the worktrees that is never versioned or pushed; `setup` creates it.
- **`gwt artifacts [<worktree>]`** command: prints/creates the folder's path (or a per-worktree subfolder).

## python — 0.1.8

### Changed

- `create`: the argument is now the **name** (provided by the caller; grove only normalizes it, doesn't derive it). If the branch already exists, the error points to `gwt track <branch>`.
- `track`: accepts **local** branches in addition to origin; is **permissive** with types outside `allowed_types` (brings them with a warning instead of requiring `--as`); the name is derived from the branch.
- `doctor`: new **`type-not-allowed`** item that is **reported** (manual) without auto-fix; no longer flags the repo base branch as out of convention.

## python — 0.1.7

First functional version of the Python implementation (`gwt`).

### Added

- Commands: `setup`, `list`, `create` (ticket / release / temp), `track`, `remove` (+ `--merged`), `sync`, `publish` (additive and `--regenerate`), `doctor`, `config`, `ssh check`.
- Bare model with parking branch `worktree-config-root`; structure by type (`feature/`, `hotfix/`, `bugfix/`, `release/`) + special branches and `temp/`.
- Per-repo configuration (`.bare/grove.toml`) and built-in profiles (`default`, `personal`, `gitflow`) + custom profiles in `~/.config/grove/config.toml`.
- Ticket policy (`required` / `optional` / `off`) and configurable keys (`ticket_prefixes` / `ticket_pattern` / `GROVE_TICKET_PREFIX`).
- Global `--json` flag with an envelope (`status`, `exit_code`, `message`, `result`, `log`).
- SSH account selection: alias detection in `setup` (`--ssh-alias`) and `config set-ssh-alias`, with `origin` rewriting.
- `ssh check` diagnostics (contextual, `--all`, `--live`), robust without `~/.ssh/config`.
- Verbose (`-v`) and `--confirm-each`; `--dry-run` on mutating operations.

## go — unreleased

Planned implementation.

## rust — unreleased

Planned implementation.
