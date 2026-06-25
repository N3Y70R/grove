# grove — usage feedback & improvement backlog

Real-world findings from dogfooding grove (CLI + MCP) on the dropi repos.
Captured manually after a lost session; kept here so they aren't lost again.

> Convention: each item has **Finding** (what happened), **Impact**, and
> **Proposed improvement** (concrete change). Items marked `→ issue` are ready
> to become GitHub issues.

## 1. Creating a worktree from a specific base branch is hard to discover

**Finding.** Needed the `temporary-unified-test` worktree to start from a
*specific* branch. The agent (via the MCP) spent a while trying combinations of
grove commands to express "create this from base X".

**Impact.** Slow, trial-and-error; the right path wasn't obvious from the tool
surface.

**Proposed improvement.**
- `create temp <name>` currently ignores base and always uses `default_base`.
  Add a `--base <branch>` option to `temp` (and expose `base` in the
  `grove_create` MCP tool for `kind="temp"`). → issue
- Document a single clear recipe: "create a worktree from an arbitrary base"
  (covering ticket/temp/release) in USAGE/TUTORIAL. → issue
- Improve MCP tool descriptions so the agent immediately knows `base` is the
  way to branch off something other than the repo default. → issue

## 2. No easy way to edit profiles / per-repo config

**Finding.** Couldn't figure out how to edit the profile configuration (e.g.
change the base branch for a repo). Editing meant hand-writing
`.bare/grove.toml` or `~/.config/grove/config.toml`, which wasn't discoverable.

**Impact.** Users get stuck on configuration; the only `config` subcommands today
are `show` and `set-ssh-alias`.

**Proposed improvement.**
- Add a generic `gwt config set <key> <value>` (and `unset`) that edits
  `.bare/grove.toml` safely — at least for `default_base`, `tickets`,
  `allowed_types`, `integration_branch`. Mirror as a `grove_config` MCP arg. → issue
- Add `gwt config edit` to open the repo config in `$EDITOR`. → issue
- Document profile editing clearly: where built-in profiles live, how to add a
  custom one in `~/.config/grove/config.toml`, and precedence. → issue

## 3. Default profile assumes base `main`, but dropi repos use `production`

**Finding.** The `default` profile points the base branch to `main`. The dropi
repos use `production` as their base, so setup/operations targeted the wrong
branch until corrected. (Note: this is dropi-specific; most personal/other repos
do use `main`, so the default itself is reasonable.)

**Impact.** Wrong base branch on managed repos until manually fixed; confusing.

**Proposed improvement.**
- On `setup`, **auto-detect the base branch from the origin** (e.g.
  `origin/HEAD` / `git remote show origin`) and use it instead of blindly taking
  the profile's `default_base`; fall back to the profile only if detection
  fails. → issue (high value)
- Ship a `dropi`-style example profile in the docs (base `production`,
  integration `temporary-unified-test`) so org repos can opt in with
  `--profile`. → issue
- When the configured base doesn't exist on origin but another common base does
  (`production`/`master`/`develop`), suggest it in the error message instead of
  just failing. → issue

## 4. Identifying the SSH aliases took a long time

**Finding.** It took the agent a while to figure out which `~/.ssh/config`
aliases (`neytor-gh`, `dropi-bb`) were in play for the repos.

**Impact.** Slow setup/diagnosis; the alias↔repo mapping wasn't surfaced.

**Proposed improvement.**
- Make alias discovery first-class and obvious from the MCP: ensure
  `grove_ssh_accounts` / `grove_ssh_check` are described so the agent reaches
  for them first; consider a tool/section that maps **repo origin → matching
  alias(es)**. → issue
- On `setup`, when the origin host has matching aliases, report them clearly
  (already partly done) and record the chosen alias in `grove.toml` so later
  operations don't have to re-discover it. → issue
- Add a short "multi-account SSH: how grove picks the key" note to the docs that
  the agent can rely on. → issue

## Cross-cutting / meta

- **MCP discoverability.** Several delays came from the agent searching for the
  right command combination. Richer tool descriptions + a couple of
  higher-level composite operations (e.g. "start working on ticket X from base
  Y") would cut trial-and-error. → issue
- **Onboarding a repo with a non-standard base** (dropi = production) should be a
  documented one-liner, not a discovery exercise.

## Candidate GitHub issues (ready to file)

1. feat(create): add `--base` to `temp` (and expose in MCP).
2. feat(setup): auto-detect base branch from `origin/HEAD`.
3. feat(config): `config set/unset/edit` for repo config keys.
4. docs: profile editing & precedence guide; add a dropi-style example profile.
5. feat(ssh): surface repo→alias mapping; persist chosen alias on setup.
6. docs/mcp: improve tool descriptions; consider a composite "start ticket from base".
