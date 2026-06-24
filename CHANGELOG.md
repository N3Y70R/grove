# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/), versioned per implementation with tags `python/vX.Y.Z`, `go/vX.Y.Z`, `rust/vX.Y.Z`.

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
