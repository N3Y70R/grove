# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/), versioned per implementation with tags `python/vX.Y.Z`, `go/vX.Y.Z`, `rust/vX.Y.Z`.

## python — 0.13.1

Follow-ups from the second review of the Agent Skill (FEEDBACK §20).

### Fixed

- **`gwt repos` / `grove_repos` agree with `grove_config`**: `origin` is the
  URL git really uses (`git remote get-url`, so a zone's `insteadOf` rewrite
  shows the SSH alias instead of the raw `https://` URL), and `profile` is the
  effective one (`default` when `grove.toml` doesn't name one) instead of `null`.

### Changed

- **The skill**: the `reset` gotcha points to "When origin moved while you
  worked" instead of repeating the `--ff-only` advice that fails on a diverged
  branch; the operation table gains `grove_publish` and `grove_ssh_check` /
  `grove_ssh_add`; the another-mount recipe moved to `troubleshooting.md` and
  the `relative_worktrees` details to `configuration.md` (one line each left in
  `SKILL.md`).

## python — 0.13.0

Feedback from reviewing the 0.12.0 Agent Skill in real use (FEEDBACK §19).

### Added

- **`gwt repos`** (MCP: `grove_repos`, read-only): lists the grove-managed repos
  under your identity zones (from `gwt ssh add`) or the folders you pass, with
  base, profile and origin — so an agent can turn "the X repo" into the `cwd`
  every tool needs. The skill says to ask for the path when nothing is found.
- **`doctor` detects an outdated Agent Skill** (`skill-outdated`): a copy in
  `~/.agents/skills` or `~/.claude/skills` written for another grove version.
  `skill install` now writes `.grove-install.json` (version + file hashes), so
  `--fix` refreshes an untouched copy and only reports an edited one (or one
  installed by 0.12.0). Outdated project copies are reported, never rewritten.

### Changed

- **The skill**: tells the agent to compare `grove_config().version` with its
  `grove-version`; a new flow step for when origin or the base moved (`behind`
  → `--ff-only`, `diverged` → `pull --rebase`, base moved → rebase or merge,
  never `reset`); explains `grove_start`'s `mode`; adds `grove_compare` and
  `grove_repos` to the operation table; warns against `git worktree add/remove`
  by hand; notes that `.bare/config` is shared; triggers in Spanish too.
- **`references/troubleshooting.md`**: rows for signed commits required
  (`GH013`), non-fast-forward after a rebase, force-push blocked by repository
  rules, and `skill-outdated`.
- `skill install` refusing an edited copy now names the installed and the
  running grove version.
- Tests run with a throwaway `HOME`, so user-level state (installed skills,
  SSH config) never leaks from the developer's machine.

## python — 0.12.0

### Added

- **grove's Agent Skill** ([agentskills.io](https://agentskills.io)) in
  [`skills/grove/`](skills/grove/SKILL.md): teaches an AI agent how to work with
  grove — which tool fits which request (`start` for tickets, `fetch` vs
  `reset`, preview before `remove --merged`, `doctor` for locks), the everyday
  flow, and a gotchas section drawn from real sessions; troubleshooting and
  configuration details load on demand from `references/`. Spec-compliant
  (validated with `agentskills validate` in CI; 86-line `SKILL.md`).
- **`gwt skill install`** (MCP: `grove_skill_install`): installs the skill
  bundled with grove into `~/.agents/skills` (default), `~/.claude/skills`
  (`--claude`), the current worktree (`--project`) or `--path DIR`. Idempotent;
  never overwrites an edited copy without `--force`, so the installed skill
  matches the installed grove version.

## python — 0.11.2

### Added

- **Typed output schemas for the remaining tools**: `grove_config` (one schema
  for show / set / unset / ssh alias, mode-specific fields optional),
  `grove_publish` and the six `grove_ssh_*` tools. All 20 MCP tools now publish
  typed, described output schemas, and the output contract test covers every one
  of them (the SSH tools against a temporary home).

## python — 0.11.1

### Added

- **Typed MCP output schemas** for the 12 everyday tools (`grove_list`,
  `grove_start`, `grove_fetch`, `grove_create`, `grove_track`, `grove_remove`,
  `grove_reset`/`grove_sync`, `grove_doctor`, `grove_compare`, `grove_setup`,
  `grove_convert`): every field with its type, allowed values (e.g. `mode`:
  existing/resumed/created; `status`: in sync/ahead/behind/diverged) and a
  description, instead of a generic "object". An agent now knows what it will
  receive before calling. Results are unchanged.

### Tests

- **Output contract test**: calls every typed tool through the MCP server on a
  real repo and checks `structured_content` equals the JSON text — the SDK
  silently drops keys a schema doesn't declare, so any drift fails the test.

## python — 0.11.0

### Added

- **Opt-in relative worktree paths**: `relative_worktrees = true` in
  `grove.toml` (`gwt config set relative_worktrees true`) makes every
  worktree's `.git` and its admin `gitdir` relative, so the repo works from any
  mount (container, VM). grove sets `worktree.useRelativePaths` in the bare —
  every later `git worktree add/move/repair` follows — and converts existing
  worktrees; `false` converts them back and removes
  `extensions.relativeWorktrees`. **Off by default** because it isn't backward
  compatible: older git (< 2.48) and libgit2 < 1.9.4 refuse such repos (verified:
  git 2.34 fails with "unknown repository extension"). grove refuses to enable it
  on an older git; profiles can carry it (`setup`/`convert` apply it, warning on
  an older git); `doctor` fixes a repo whose paths don't match the setting.

### Tests / CI

- Tested against a real git 2.51 (the full suite passes on it too); the CI now
  prints `git --version` and the reasons for skipped tests.

## python — 0.10.0

### Changed

- **No more internal parking branch.** grove used to create
  `worktree-config-root` and point the bare's `HEAD` at it, so the base branch
  stayed free for its own worktree — leaving an internal branch among the
  user's branches. git doesn't need it (a bare `HEAD` doesn't occupy its branch;
  verified on git 2.34), so `setup` and `convert` now point the bare `HEAD` at the
  base, and plain `git log` from the repo root shows the base. New `grove.toml`
  files no longer carry `parking_branch` (still read, to migrate old repos).

### Added

- **`doctor` migrates existing repos**: a bare `HEAD` that doesn't point at the
  base (`bare-head`: the legacy parking branch, or a dangling `HEAD`) is
  re-pointed, and the legacy `worktree-config-root` branch is deleted when it
  has no commits outside the base and no worktree (`parking-branch`); otherwise
  it is only reported. Run `gwt doctor --fix` once per existing repo.

## python — 0.9.2

### Added

- **`gwt start`** (MCP: **`grove_start`**): start or resume work on a ticket in
  one idempotent call — fetch, then return the ticket's existing worktree
  (`existing`), bring its branch if it exists locally or on origin (`resumed`), or
  create it from the freshly fetched `origin/<base>` (`created`). Returns path,
  branch, base, upstream, gitdir and next steps; refuses ambiguous tickets. It is
  the composite operation the feedback asked for ("start ticket X from base Y").

### Fixed

- **A branch created from a remote base tracked it**: `create --base origin/x`
  (and any start point that is a remote-tracking ref) made `origin/x` the new
  branch's upstream, so `git pull` pulled the base and `list` measured against
  it. New branches are now created with `--no-track`.

## python — 0.9.1

### Added

- **Structured MCP results**: every tool now returns `structured_content` (the
  result object) with an object output schema, besides the same data as JSON
  text — so clients can read the result directly instead of parsing text. It
  only took typing the tools' return as `dict[str, Any]` (with a bare `dict`
  the SDK sends text only). Text-only clients see no difference. Enforced by the
  schema test and checked end to end over stdio.

## python — 0.9.0

### Changed

- **MCP server migrated to mcp 2.x**: the `[mcp]` extra now requires
  `mcp>=2.2,<3` (it was capped `<2` since 0.6.1). The server uses `MCPServer`
  (FastMCP's new name) and snake_case annotation fields. **Nothing changes for
  clients**: same tools, parameters, descriptions and annotations, and results
  still arrive as JSON text (verified against mcp 1.30). Upgrade with
  `pipx install --force "grove-wt[mcp]"` (or reinstall your environment) and
  restart the MCP client.

### Fixed

- **A repo without `grove.toml` got grove's internal work-style defaults**
  (base `production`, tickets `required`) in any new process. It now uses the
  `default` profile, as documented in 0.8.2. Found by the new end-to-end test.

### Tests

- **End-to-end MCP test**: starts `python -m grove.mcp` over stdio (as Claude
  Desktop does), initializes, lists the tools and calls `grove_config` on a real
  repo.

## python — 0.8.4

### Changed

- **`cli/main.py` split into one module per area** (no behavior change):
  `grove/cli/commands/{repo,worktrees,remote,maintenance,ssh}.py`, each command
  as a `cmd_<name>` handler + `register_<name>(sub)` subparser pair, shared
  helpers in `cli/_shared.py`, and `cli/main.py` down from ~1,480 to ~110 lines.
  Verified by the full test suite and a byte-for-byte comparison of the `--help`
  output of all 30 commands and subcommands. The unused `_not_implemented`
  stub was removed.

## python — 0.8.3

### Added

- **`gwt fetch [--prune]`** (MCP: `grove_fetch`): brings what's new on origin
  and shows every worktree's ahead/behind and status — **without touching any
  worktree**. It is the safe counterpart of `reset`; it used to exist only as a
  side effect of `compare --fetch`, where nobody looking for "update" found it.
  The hints in `reset`/`sync` and the docs now point to it.

## python — 0.8.2

Theme: **documentation for the questions that keep coming up** (and a bug it
uncovered).

### Fixed

- **`gwt config unset` fell back to grove's internal work-style defaults**
  (base `production`, tickets `required`) instead of the repo's profile: in a
  `personal` repo, unsetting `default_base` made the base `production`. The repo
  now records its profile (`profile = "<name>"` in `grove.toml`, written by
  `setup`/`convert`), and every command layers that profile before the repo's
  keys. Repos without the key use the `default` profile; an unknown profile
  falls back to `default` too.

### Documentation

- **Recipes** in USAGE: create from any base, adopt an existing clone, bring
  remote changes safely, clean up merged work, clear a git lock.
- **Configuration**: how the effective policy is really built, "a profile is a
  template", an editing cheat sheet and a work-style profile example; advice to
  set `ticket_prefixes`.
- **How git picks the SSH key** (TUTORIAL): host in the URL → `~/.ssh/config`,
  and where grove's per-repo alias and per-folder zones fit.
- **Release process** (CONTRIBUTING): release commit last, CI, fast-forward,
  tag after merge, stale-PyPI-index check; the same check in INSTALL.

## python — 0.8.1

Theme: **robustness** — fail with a way out, not with a raw git error.

### Fixed

- **`git config --global` no longer depends on the current directory**: `ssh add`,
  `ssh doctor` and the identity helpers run it from `$HOME`. Inside a folder whose
  `.git` is broken (a worktree seen from another mount, a deleted repo) they used
  to fail with "not a git repository".
- **A missing base branch gets a suggestion**: `create` (ticket/release/temp)
  used to fail with git's raw `Not a valid object name`; it now names the
  existing candidates and the fix (`--base <candidate>`, or
  `gwt config set default_base <candidate>` when the repo's configured base is
  the one missing). `setup` lists the branches on origin when neither the
  requested base nor origin's default branch exist.

### Changed

- **CI tests Python 3.11–3.14** (pipx installs grove with 3.14 on macOS); the
  PyPI classifiers now list 3.13 and 3.14.

## python — 0.8.0

Theme: **read `list` without guessing**.

### Changed

- **`ahead`/`behind` are measured against the base when there is no upstream**
  (they used to be `null`, which hid the pending work of every new branch). A new
  `compared_to` field says what they are measured against (`origin/main` vs
  `main`); the table shows `↑3 ↓0 vs main (no upstream)`. The `reset` warning
  words those commits accordingly instead of calling them "not pushed".
- **The base worktree is `kind: "base"`** (it was `unknown` with the
  `default`/`personal` profiles and `special` when the base is also a special
  worktree). It is **protected from `remove`** like the special ones — before,
  with `default`/`personal`, `remove main` was allowed.

### Fixed

- **Worktrees seen from another mount are no longer orphans.** git records
  absolute paths, so from a container/VM `list` reported them as missing and
  prunable, and `doctor --fix` would run `git worktree prune`, unregistering
  them. `list` now finds the local folder and reports correct `path`/`rel_path`
  with `exists: true`, `prunable: false`.

## python — 0.7.1

Theme: **find what already exists** — the recurring root cause in the feedback
was naming (users searched for `grove`, for "adopt", for "update").

### Added

- **`grove` command**: installed as an alias of `gwt`, so typing the project's
  name works.
- **`gwt adopt`**: alias of `gwt convert`, for users who think "adopt my clone".
- **`setup` points at `convert`**: when the destination is already a git clone,
  the error suggests `gwt convert <path>` instead of just "already exists".
- **Version visible from the MCP**: `grove_config` and `grove_doctor` (and their
  `--json` CLI counterparts) include `version`.
- **CLI equivalent in every MCP tool**: each description ends with a
  ``CLI: `gwt …` `` line (enforced by a schema test), so an agent can tell the user
  how to do the same in the terminal.

## python — 0.7.0

Theme: **don't lose work by accident** — every destructive operation can now be
previewed, and the command that discards work says so in its name.

### Changed

- **`gwt sync` is now `gwt reset`** (MCP: `grove_reset`). "sync" read as "update
  from the remote", but the command does `fetch` + `reset --hard` and **discards**
  local commits and changes. `gwt sync` / `grove_sync` still work as deprecated
  aliases (the CLI prints a warning; the MCP result carries
  `"deprecated": "use grove_reset"`) and will be removed in a future release.
- **`compare` says it can fetch**: its help and MCP description now lead with
  `--fetch` / `fetch=true` as the *safe* way to bring remote changes.
- **`remove` cleans up empty folders**: parent folders left empty after removing
  a worktree (e.g. `feature/`) are removed, up to the repo root.

### Added

- **`merged` in `list`** (`--json`, `grove_list`, and a `merged` marker in the
  table status): `true` when the branch has no commits outside the base — exactly
  what `remove --merged` would sweep. Note that a brand-new branch with no commits
  of its own also counts as merged.
- **`dry_run` in `grove_remove`** (MCP parity with the CLI's `--dry-run`):
  reports what would be removed without changing anything, and needs no
  `confirm`.

## python — 0.6.2

### Added

- **`doctor` cleans up leftover git locks and temp objects.** Orphaned `*.lock`
  files anywhere in `.bare` (e.g. the `HEAD.lock` behind *"Another git process
  seems to be running"*) and interrupted-write leftovers (`tmp_obj_*`,
  `tmp_pack_*`, `tmp_idx_*`) are now reported and removed by `--fix` — only when
  stale: ≥60 s old with no git process running on this machine, or ≥10 min old
  regardless. Recent locks are reported for manual review and never touched.
  Lock fixes run first, since a lock makes every other git-based fix fail.
- **`doctor` reports missing author identity**: worktrees where
  `git var GIT_AUTHOR_IDENT` fails (a commit would fail with *"Author identity
  unknown"*). Manual; honours `includeIf` zones.
- **`gitdir` in `list`** (`--json` and `grove_list`): each worktree's internal
  admin directory relative to the repo root (e.g. `.bare/worktrees/PROJ-1-login`).
  git names it after the last path component, so it can't be derived from the
  folder; it lets tools on another mount build `GIT_DIR`.

### Changed

- CLI `list --json` and MCP `grove_list` now build their rows from one shared
  function (`model.worktree_dict`), so both always expose the same fields.

## python — 0.6.1

### Fixed

- **`grove-mcp` failed to start with mcp 2.x.** The `mcp` extra was unbounded,
  so fresh installs pulled mcp 2.x, where `FastMCP` was renamed. The extra is
  now pinned to `mcp>=1.2,<2` until the server is migrated to the 2.x API.
- **Clearer MCP import error**: it now distinguishes "SDK not installed" from
  "incompatible SDK version", recommends the correct extra
  (`pip install "grove-wt[mcp]"`), and raises `ImportError` instead of
  `SystemExit` so importers (e.g. pytest) report it cleanly.
- **`convert` left folders behind at the repo root.** A tracked folder that also
  held ignored files (e.g. `python/.venv`) was classified only by its top-level
  name and then silently skipped because the worktree already had that folder,
  leaving tracked duplicates and ignored files orphaned at the root. The cleanup
  now merges path by path: ignored files move into the current worktree, tracked
  duplicates are dropped, and any conflict is kept at the root and reported.
- **`convert` now writes `.bare/grove.toml`** (as the design required), with the
  detected base; new `--profile` (CLI) / `profile` (MCP) chooses the policy.
- **Versions were parsed as tickets**: `fix/python-0.6.1` yielded ticket
  `PYTHON-0`. Ticket keys are now anchored at token boundaries (no digit or
  `.<digit>` right after the key).
- **Wrong command in the "no managed repo" error** (`wt setup` → `gwt setup`, and
  it now mentions `gwt convert`).
- **Tests no longer depend on the host environment**: the suite isolates the
  global git config (pins `init.defaultBranch=main`) and hides the developer's
  ssh-agent, which made SSH doctor tests fail locally while passing in CI.

## python — 0.6.0

### Changed

- **`setup` and `convert --into` are now transactional**: if they fail partway
  through, the partial repo folder they created is removed automatically, so a
  retry starts clean instead of hitting "destination already exists" or leftover
  `.bare/`. Use `--keep-on-error` (CLI) / `keep_on_error` (MCP) to preserve the
  partial state for debugging. In-place `convert` never auto-deletes (it could
  discard files already moved into a worktree): it restores the auto-stash if it
  fails before any change, and otherwise stops and reports so you can inspect.

### Added

- **`gwt convert`** — turn an existing normal clone into the grove model without
  re-cloning. In-place by default (reuses `.git`, auto-stashes/restores
  uncommitted work, preserves ignored files, keeps local branches/stashes);
  `--into <dir>` builds beside the source leaving it untouched; `--branches
  current|current+base|all`; submodules/Git LFS refused unless `--force`;
  `--dry-run`. Exposed as the `grove_convert` MCP tool.
- **Root `.git` pointer** (`gitdir: ./.bare`) written by `setup` and `convert` by
  default so plain `git` works from the repo root; disable with `--no-git-pointer`.
- **`doctor` heals a missing root `.git` pointer** (new auto-fixable
  `git-pointer` check), so repos created before this feature (or by hand) can be
  fixed with `gwt doctor --fix`.
- **`gwt config set | unset | edit`** — change the per-repo `grove.toml` without
  hand-editing: `set <key> <value>` (list keys like `allowed_types` take a
  comma-separated value; `ticket_prefixes`/`ticket_pattern` stay mutually
  exclusive), `unset <key>` (reverts to the profile default), and `edit` (opens
  `grove.toml` in `$EDITOR`). `set`/`unset` are exposed in the `grove_config` MCP
  tool via `set_key`/`set_value`/`unset_key`.
- **`gwt ssh aliases [<url-or-host>]`** — repo↔alias map: lists the
  `~/.ssh/config` aliases whose `HostName` resolves to a repo's origin host (or a
  given URL/host), resolving the real host when the origin already uses an alias
  and marking the one currently applied. Removes the guesswork of "which alias
  does this repo need?". Exposed as the read-only `grove_ssh_aliases` MCP tool.

## python — 0.5.0

### Changed

- **PyPI distribution name is `grove-wt`** (`grove` was already taken by an
  unrelated project). The imported package is still `grove` and the commands are
  still `gwt` and `grove-mcp`; only the install label changes
  (`pipx install grove-wt`, `pipx upgrade grove-wt`).

### Added

- **Publishing**: a release workflow (`.github/workflows/release.yml`) that, on a
  `python/v*` tag, builds the sdist+wheel and publishes to **PyPI** and creates a
  **GitHub Release** with the artifacts.
- **Richer MCP tool schemas (agent discoverability)**: every tool now carries
  per-parameter descriptions, enums for constrained choices (`grove_create.kind`),
  and MCP annotations (read-only / destructive / idempotent, `openWorldHint=false`).
  A schema test (`test_mcp_schema.py`) enforces that every parameter is described,
  and CONTRIBUTING documents keeping the MCP enriched as part of the definition of
  done.
- **`publish --regenerate` creates the integration branch when missing**: it now
  locates the branch (worktree → origin → local) and, if it exists nowhere,
  **creates it from `--base`** with a normal push (no force/confirmation). Targets
  are optional with `--regenerate`, so `gwt publish --regenerate --base <branch>`
  seeds an empty integration branch. Rebuilding an existing branch still
  force-pushes with confirmation. One command now both creates and rebuilds the
  integration branch (exposed in the `grove_publish` MCP tool; result carries
  `created` and `mode`).
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
