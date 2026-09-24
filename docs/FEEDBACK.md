# grove — usage feedback & improvement backlog

Real-world findings from dogfooding grove (CLI + MCP) on the dropi repos.
Captured manually after a lost session; kept here so they aren't lost again.

> Convention: each item has **Finding** (what happened), **Impact**, and
> **Proposed improvement** (concrete change). Items marked `→ issue` are ready
> to become GitHub issues. Each item carries a **Status** line; the prioritized
> view is the [backlog table](#backlog-prioritized) at the end.

**Sources.** Items 1–4: first dogfooding session on the dropi repos. Items 5–17
(added 2026-09-23): onboarding `dropi-business-rules` with ticket worktrees
(team notes, `grove-hallazgos.md`) and converting grove's own clone with
`gwt convert`. Everything was re-checked against the code of **python 0.6.1**;
claims of the form "grove can't do X" were verified before being written, since
several first drafts turned out to be "we didn't find how to do X".

## 1. Creating a worktree from a specific base branch is hard to discover

**Status:** ✅ done — `create temp --base` and base-aware MCP descriptions
(0.5.0); "create a worktree from any base" recipe in USAGE (0.8.2).

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

**Status:** ✅ done — `config set | unset | edit` (0.6.0); editing guide and the
real precedence in USAGE, and `unset` falling back to the repo's profile (0.8.2).

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

**Status:** ✅ done — `setup` auto-detects the origin base (0.5.0); `convert`
records it (0.6.1); missing-base suggestions (0.8.1); work-style profile example
in USAGE (0.8.2).

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

**Status:** ✅ done — `gwt ssh aliases` / `grove_ssh_aliases` (0.6.0); `setup
--ssh-alias` persists the alias; "How git picks the key" in TUTORIAL (0.8.2).

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

## 5. `convert` exists but isn't found; it had two bugs (fixed in 0.6.1)

**Finding.** A team onboarding an existing clone moved it aside and re-cloned
with `setup`, then wrote down "grove needs an `adopt` command". `gwt convert`
(0.6.0) already does exactly that. Using `convert` on grove's own clone then
exposed two bugs: a tracked folder that also held ignored files
(`python/.venv`) was classified by its top-level name and silently skipped,
leaving 47 MB orphaned at the root; and `convert` never wrote `grove.toml`.

**Impact.** Unnecessary re-clones; after conversion, the repo ran on built-in
defaults (base `production`, tickets required) instead of a real policy.

**Proposed improvement.**
- ✅ 0.6.1: path-by-path relocation (conflicts kept and reported), `grove.toml`
  written, `--profile` / `profile`.
- When `setup`'s destination is already a clone, suggest `gwt convert` in the
  error (the "no managed repo" error already does since 0.6.1). → issue
- Consider `adopt` as an alias of `convert`. → issue

## 6. `doctor` misses orphaned locks, temp objects and a missing identity

**Finding.** With `.bare/objects/maintenance.lock`, a worktree `HEAD.lock` and
`tmp_obj_*` files present, `doctor` returned `issues: []`; the next `git`
command failed with "Another git process seems to be running". Seen twice (both
left by an environment without delete permission). Separately, a first commit
failed with "Author identity unknown" after onboarding.

**Impact.** Hygiene problems surface at the worst moment (mid-commit), and
nobody knows those files are safe to delete.

**Proposed improvement.**
- `doctor` reports orphaned `*.lock` (no running git) and
  `objects/**/tmp_obj_*`; `--fix` removes them. → issue
- `doctor` checks that `user.email` resolves for the repo and its worktrees. →
  ✅ 0.6.2. *(Verified 2026-09-23: the original failure was not grove's — a
  fresh repo under the dropi zone resolves the identity from grove's zone file;
  the assisted environment simply can't see the Mac's `~/.gitconfig`.)*

## 7. Worktree `.git` files use absolute paths

**Finding.** `gitdir: /Users/…/.bare/worktrees/<wt>` is unusable when the repo
is seen from another mount (container, VM, assisted session). The workaround is
passing `GIT_DIR`/`GIT_WORK_TREE` by hand, and the internal name is the *last
path component* (git's rule), so it can't be derived from the visible path
(`feature/X` → `.bare/worktrees/X`). From the other mount, git even reports
the worktrees as **prunable**: a `git worktree prune` there would unregister
them. grove's own tests hit this (they run `git config --global` from a cwd
inside a broken worktree).

**Impact.** Any tool or agent working from a second filesystem can't use git
in worktrees, and can destroy their registration by "cleaning up".

**Proposed improvement.**
- Cheap, do first: expose the internal `gitdir` path in `list` (CLI + MCP). →
  issue
- Opt-in relative paths: `relative_worktrees = true` in `grove.toml` →
  `git worktree add --relative-paths`. Requires git ≥ 2.48 (the Mac has 2.54;
  the assisted environment has 2.34) and is **not backward compatible**:
  libgit2 < 1.9.4 tools (e.g. TortoiseGit) and older git can't read such repos.
  Off by default; `doctor` warns when enabled on an older git. → issue
- `rel_path` is computed from the absolute path git recorded, so from another
  mount it comes out as `../../../../Users/…` (seen 2026-09-23 while testing
  `gitdir`). Derive it from the admin dir instead (the worktree's `.git` sits at
  `<root>/<rel_path>`), or fall back to matching by the recorded path's suffix
  under the repo root. → issue
- Run machine-level git commands (`git config --global`, used by `ssh add`)
  with a neutral cwd (`$HOME`) so a broken repo in the cwd can't break them. →
  issue

## 8. The fetch is hidden; `sync` sounds like "update" but discards

**Finding.** The most repeated operation with several worktrees — bring what's
on the remote — only exists as `compare --vs <ref> --fetch`, whose description
starts with "read-only". Meanwhile `sync` does `reset --hard` to origin: a
worktree with 984 unpushed migrated rules was one `sync` away from losing them.
(The MCP description of `grove_sync` does say DESTRUCTIVE; the CLI name is the
trap.)

**Impact.** Users don't find the safe operation and do find the dangerous one
under the word they were looking for.

**Proposed improvement.**
- A `gwt fetch` verb (same as `compare --fetch` without the comparison), or at
  least mention the fetch first in `compare`'s description. → issue
- Rename `sync` to something that says what it does (`reset`/`discard`), keeping
  `sync` as a deprecated alias; its help should start with "Discards". → issue

## 9. `list` doesn't say whether a worktree is merged

**Finding.** Before removing a worktree, the question is always "is this
already in the base?". `list` doesn't answer it; we checked by hand with
`git merge-base --is-ancestor`. `remove --merged` computes it, and the CLI has
`remove --merged --dry-run` — but the MCP `grove_remove` has no `dry_run`.

**Impact.** The data behind the only sweeping destructive action can't be seen
beforehand from the assistant.

**Proposed improvement.**
- `merged` field in `list` (vs the repo base), also as a CLI column/flag. → issue
- `dry_run` parameter in `grove_remove` (MCP parity with the CLI). → issue

## 10. `ahead`/`behind` are `null` without an upstream

**Finding.** A new branch six commits ahead of `main`, not pushed yet, showed
`ahead: null, behind: null`. Technically right; useless in the most common case
of a ticket-per-worktree repo.

**Proposed improvement.** Without upstream, measure against the base and say so
(`ahead: 6 (vs base)`; in JSON, add `compared_to: "base"`). → issue

## 11. The project is "grove" everywhere; the command is `gwt`

**Finding.** Package (`grove-wt`), repo, config file, MCP server and docs say
grove; the binary is `gwt`. Typing `grove` gives "command not found" and the
conclusion "it isn't installed". grove itself printed a third name (`wt setup`)
until 0.6.1.

**Proposed improvement.**
- Install a `grove` entry point as an alias of `gwt`. → issue
- MCP tool descriptions mention the equivalent CLI command. → issue

## 12. `worktree-config-root` looks like a user branch

**Status:** ✅ done in 0.10.0 — the branch is gone: the bare `HEAD` points at the
base (a bare `HEAD` doesn't occupy its branch), and `doctor --fix` migrates old repos.

**Finding.** The parking branch lives in `refs/heads`, next to real branches,
pointing to an old commit. In a repo with many branches someone will sweep it.

**Proposed improvement.** Point the bare `HEAD` at an **unborn** branch (never
created) or move it to `refs/grove/*` — test first what git accepts as a bare
`HEAD`. Meanwhile, `doctor` recognizes and explains it. → issue

## 13. The base worktree shows `kind: "unknown"`

**Finding.** With profiles whose `special_worktrees` doesn't list the base
(`default`, `personal`), `main` is classified `unknown`, though `setup` created
it.

**Proposed improvement.** Classify the configured base as `kind: "base"`. → issue

## 14. `remove` leaves empty type folders

**Finding.** Removing the only `fix/…` worktree left an empty `fix/` folder at
the root.

**Proposed improvement.** Remove parent folders left empty, up to the repo root
(never `.bare`, the base or `artifacts/`). → issue

## 15. The version isn't visible from the MCP

**Finding.** `gwt --version` exists, but no MCP tool returns the version, so
findings written from the assistant can't be dated to a release.

**Proposed improvement.** Include `version` in `grove_config` and
`grove_doctor` results. → issue

## 16. The generic ticket pattern is permissive

**Finding.** `fix/python-0.6.1` was read as ticket `PYTHON-0` (fixed in 0.6.1:
keys must end at a boundary). With `tickets = "optional"` and no prefixes, any
`word-number` still passes as a ticket.

**Proposed improvement.** Document `ticket_prefixes` as the recommended setting;
consider not extracting tickets at all when `tickets = "off"`. → issue

## 17. Maintenance / tech debt

- **mcp 2.x:** ✅ 0.9.0 (`mcp>=2.2,<3`, `MCPServer`); structured results ✅ 0.9.1.
- **`cli/main.py` is ~1,450 lines**: split into one module per command. → issue
- **Releases:** document "tag after merge, never squash/rebase-merge a release
  branch" so the `python/vX.Y.Z` tag stays on `main`. → issue
- **Releases, install side:** after publishing, some networks keep serving a
  stale PyPI index for a long time (seen for 0.6.2 and 0.7.0: pypi.org already
  listed the version, `pip` on the Mac did not). `pipx install --force grove-wt`
  then silently *downgrades*. Document: check `pipx runpip grove-wt index
  versions grove-wt` first, or install from the local `main` checkout. → issue

## 18. Ship grove's know-how as an Agent Skill

**Status:** ✅ done in 0.12.0 — `skills/grove/` + `gwt skill install`. Open: trim
workflow advice from the MCP tool descriptions once the skill is widely installed.

**Finding.** The MCP tells an agent *which tools exist*; it doesn't teach *how
to work* with grove: the recommended flow, which tool fits which request, and
the traps. Most dogfooding delays were exactly that (items 5, 8, 11): `adopt`
already existed as `convert`, `sync` sounded safe but discarded work, the
safe fetch hid inside `compare`, `grove` vs `gwt`. [Agent Skills](https://agentskills.io/specification)
is an open format (a folder with a `SKILL.md`: `name` + `description`
frontmatter and Markdown instructions, optional `scripts/`, `references/`,
`assets/`) read by Claude/Claude Code, Codex, Gemini CLI, Cursor, Copilot, VS
Code and others, loaded progressively (only name + description at startup; the
body when a task matches; references on demand). The shared install location is
`.agents/skills/` (project or user level); many clients also read
`.claude/skills/`.

**Impact.** Every agent rediscovers grove by trial and error; workflow
guidance is squeezed into MCP tool descriptions, which load on every session.

**Proposed improvement.**
- Ship `skills/grove/SKILL.md` in the repo, following the spec: `name: grove`,
  a keyword-rich `description` (worktrees, tickets, `gwt`, "start working on
  ticket X"), body under 500 lines with the core flow (`start` → work → push →
  `remove --merged`, `fetch` vs `reset`, `doctor --fix`) and a **gotchas**
  section taken from real sessions (`reset` discards; never touch repos the
  user didn't ask for; `relative_worktrees` breaks git < 2.48; sandbox locks →
  `doctor --fix`; `GIT_DIR` from another mount; restart the MCP client after
  upgrading; stale PyPI index). Detail goes to `references/` (one level deep,
  loaded "when X happens"). → issue
- Validate it in CI with `skills-ref validate skills/grove`, and document how
  to install it (copy/symlink to `~/.agents/skills/grove` or
  `~/.claude/skills/grove`). → issue
- Later: `gwt skill install [--user|--project] [--path DIR]` copies the bundled
  skill (packaged with the wheel) to the chosen skills directory, so it matches
  the installed grove version. → issue
- Once the skill exists, trim workflow advice from the MCP tool descriptions
  where the skill covers it (keep descriptions about *what* each tool does).

## 19. Feedback on the Agent Skill (review of 0.12.0)

**Status:** ✅ done in 0.13.0.

**Finding.** A review of the 0.12.0 skill (every tool and parameter checked
against the live MCP server: no technical errors) found gaps, not mistakes:

- **S1 — no way to notice a stale skill or server.** The skill carries
  `grove-version`, `grove_config` returns `version`, and nothing connects them.
  During the review itself the MCP server kept running old code for twenty
  minutes after an upgrade; a version mismatch was almost reported that didn't
  exist. `skill install` also refuses an outdated edited copy without saying so.
- **S2 — the flow stops where real work happens:** a multi-day ticket whose
  base moved. The only advice (`fetch` + `git merge --ff-only`) fails exactly
  when `grove_fetch` reports `diverged`.
- **S3 — "the repo" can't be resolved to a path.** The skill demands `cwd` and
  warns that several grove repos coexist, but there is no verb to list them.
- **S4 — triggers only in English;** the team writes "arranquemos el
  TECH-1400", "traigamos lo de origin".
- **S5 — `troubleshooting` misses the first-push failures** that happen in the
  step the skill tells the agent to run: signed commits required (`GH013`),
  non-fast-forward after a rebase, force-push blocked by repository rules.
- **S6 — `mode` is mentioned but never explained** (`resumed` may bring
  someone else's commits).
- **S7 — minor:** `grove_compare` missing from the operation table; no warning
  against `git worktree add/remove` by hand; nothing says the config in
  `.bare/config` is shared by every worktree.

**Proposed improvement.**
- S1: every install writes `.grove-install.json` (version + file hashes);
  `doctor` reports `skill-outdated` for user-level copies, refreshes untouched
  ones with `fix`, and only reports edited or project copies; the skill tells
  the agent to compare `grove_config().version` with its `grove-version`.
- S3: `gwt repos` / `grove_repos` — search the identity zones (or given folders)
  for `.bare/`; the skill says to ask for the path when it finds nothing.
- S2, S4–S7: skill text and `references/troubleshooting.md`.

## 20. Agent Skill, second review (0.13.0)

**Status:** ✅ R1–R3 done in 0.13.1; item 37 (`repos_roots`) open.

**Finding.** All of §19 verified live. Left, and small:

- **R1 — `grove_repos` and `grove_config` disagree on the same repo.** `repos`
  read the raw `remote.origin.url` (`https://github.com/…`) while `config` uses
  `git remote get-url` (the zone's `insteadOf` applied: `git@dropi-gh:…`); and
  `repos` returned the `profile` written in `grove.toml` (`null` when absent)
  while `config` shows the effective one (`default`). An agent using `repos`'s
  origin would bypass the SSH alias `setup` configured.
- **R2 — the `reset` gotcha repeated the old advice** (`fetch` + `--ff-only`),
  which fails on a diverged branch; the full flow is a section below.
- **R3 — `publish` and the SSH tools weren't in the operation table.**
- Size: `SKILL.md` grew to 7 KB; the two longest gotchas (another mount,
  `relative_worktrees`) belong in `references/`.
- From using `grove_repos`: repos outside an identity zone (personal repos
  reached through an SSH alias without a zone) are only found by passing
  their folder.

**Proposed improvement.**
- R1: `repos` reports the effective origin (`remote get-url`) and profile.
- R2: the gotcha points to "When origin moved while you worked".
- R3: table rows for `grove_publish` and `grove_ssh_check` / `grove_ssh_add`.
- Move the mount recipe to troubleshooting and the `relative_worktrees`
  details to configuration; one line each in `SKILL.md`.
- Later: a `repos_roots` list in `~/.config/grove/config.toml` — extra folders
  `gwt repos` searches besides the zones. → issue

**Found releasing 0.13.1:** `gwt skill install` refused the untouched 0.13.0
copies ("installed copy is for grove 0.13.0 … Re-run with force") — the
manifest existed, but only `doctor` consulted it. Fixed in 0.13.2 (item 38).

## Cross-cutting / meta

- **MCP discoverability.** Several delays came from the agent searching for the
  right command combination. Richer tool descriptions (✅ 0.5.0) + a couple of
  higher-level composite operations (e.g. "start working on ticket X from base
  Y") would cut trial-and-error. → issue
- **Onboarding a repo with a non-standard base** (dropi = production) should be a
  documented one-liner, not a discovery exercise.
- **Agent-facing knowledge has three layers**: typed MCP schemas (what each
  tool returns, ✅ 0.11.x), tool descriptions (what each tool does, with its
  `CLI:` line) and an Agent Skill (how to work with grove, §18), which must
  stay in step with the running grove (§19).
- **Naming is the recurring root cause** (items 5, 8, 11): `convert` vs "adopt",
  `sync` vs "update", `gwt` vs "grove". Before adding features, check whether the
  capability exists under a name users don't search for.

## Backlog (prioritized)

Open items, most valuable first. "Size" is a rough guess (S ≤ half a day, M ≤ 2
days, L more).

| # | Item | Source | Size |
|---|---|---|---|
| 1 | ~~`doctor`: orphaned locks + `tmp_obj_*` (auto-fix), identity check~~ ✅ 0.6.2 | §6 | S |
| 2 | ~~`gitdir` field in `list`~~ ✅ 0.6.2 | §7 | S |
| 3 | ~~Rename `sync` (keep deprecated alias); fetch mentioned first in `compare`~~ ✅ 0.7.0 (`reset`) | §8 | S |
| 4 | ~~`merged` in `list`; `dry_run` in `grove_remove`~~ ✅ 0.7.0 | §9 | S |
| 5 | ~~Neutral cwd for machine-level git commands~~ ✅ 0.8.1 | §7 | S |
| 6 | ~~`setup` error suggests `convert`; `adopt` alias~~ ✅ 0.7.1 | §5 | S |
| 7 | ~~`grove` entry point alias; CLI equivalent in MCP descriptions~~ ✅ 0.7.1 | §11 | S |
| 8 | ~~`ahead`/`behind` vs base when no upstream~~ ✅ 0.8.0 | §10 | S |
| 9 | ~~`remove` cleans empty parent folders~~ ✅ 0.7.0 | §14 | S |
| 10 | ~~`version` in `grove_config` / `grove_doctor`~~ ✅ 0.7.1 | §15 | S |
| 11 | ~~`kind: "base"` for the base worktree~~ ✅ 0.8.0 (also protected from `remove`) | §13 | S |
| 12 | ~~`gwt fetch` verb~~ ✅ 0.8.3 | §8 | S |
| 13 | ~~Opt-in relative worktree paths (`relative_worktrees`)~~ ✅ 0.11.0 | §7 | M |
| 14 | ~~Parking branch out of `refs/heads`~~ ✅ 0.10.0 — removed: bare `HEAD` → base; `doctor` migrates | §12 | M |
| 15 | ~~Migrate to mcp 2.x~~ ✅ 0.9.0 | §17 | M |
| 16 | ~~Split `cli/main.py`~~ ✅ 0.8.4 | §17 | M |
| 17 | ~~Composite MCP op "start ticket X from base Y"~~ ✅ 0.9.2 (`gwt start` / `grove_start`) | meta | M |
| 18 | ~~Docs: arbitrary-base recipe, profile editing & precedence, work-style profile, SSH key selection, ticket prefixes, release tagging~~ ✅ 0.8.2 | §1–4, §16, §17 | M |
| 19 | ~~Suggest an existing base when the configured one is missing~~ ✅ 0.8.1 | §3 | S |
| 20 | ~~`rel_path` correct from another mount~~ ✅ 0.8.0 (and never prunable/orphan there) | §7 | S |
| 21 | ~~CI matrix: add Python 3.13 and 3.14 (pipx installs with 3.14)~~ ✅ 0.8.1 | — | S |
| 22 | ~~Structured MCP results so clients get `structured_content`, not only JSON text~~ ✅ 0.9.1 | §17 | S |
| 23 | ~~Typed output schemas (fields, types, descriptions) for the everyday MCP tools~~ ✅ 0.11.1 | §17 | M |
| 24 | ~~Typed output schemas for `grove_config`, `grove_publish` and `grove_ssh_*`~~ ✅ 0.11.2 | §17 | M |
| 25 | ~~Agent Skill `skills/grove/SKILL.md`, `skills-ref` validation in CI, install docs~~ ✅ 0.12.0 | §18 | M |
| 26 | ~~`gwt skill install`: install the bundled skill matching the grove version~~ ✅ 0.12.0 (`--claude`, `--project`, `--path`) | §18 | S |
| 27 | ~~S1: detect an outdated skill — install manifest, `doctor` `skill-outdated` (auto-refresh untouched copies), version check in the skill~~ ✅ 0.13.0 | §19 | S |
| 28 | ~~S2: flow step "origin moved" — `behind` / `diverged` / base moved, never `reset`~~ ✅ 0.13.0 | §19 | S |
| 29 | ~~S3: `gwt repos` / `grove_repos` to resolve a repo name to its path~~ ✅ 0.13.0 | §19 | S |
| 30 | ~~S4: Spanish triggers in the skill description~~ ✅ 0.13.0 | §19 | S |
| 31 | ~~S5: troubleshooting rows for `GH013` signatures, non-fast-forward after rebase, blocked force-push~~ ✅ 0.13.0 | §19 | S |
| 32 | ~~S6: explain `grove_start`'s `mode` (`existing` / `resumed` / `created`)~~ ✅ 0.13.0 | §19 | S |
| 33 | ~~S7: `grove_compare` in the table; no manual `git worktree add/remove`; shared `.bare/config`~~ ✅ 0.13.0 | §19 | S |
| 34 | ~~R1: `repos` reports the effective origin (`remote get-url`) and profile, like `config`~~ ✅ 0.13.1 | §20 | S |
| 35 | ~~R2: the `reset` gotcha points to the "origin moved" flow~~ ✅ 0.13.1 | §20 | S |
| 36 | ~~R3: `publish` and `ssh_*` in the operation table; long gotchas moved to `references/`~~ ✅ 0.13.1 | §20 | S |
| 38 | ~~`skill install` refreshes an untouched outdated copy without `--force`~~ ✅ 0.13.2 | §20 | S |
| 37 | `repos_roots` in `~/.config/grove/config.toml`: extra folders for `gwt repos` besides the identity zones | §20 | S |

**Done** (for the record): `create temp --base`, richer MCP schemas, `setup`
base auto-detection (0.5.0); `config set/unset/edit`, `ssh aliases`,
`convert` (0.6.0); `convert` fixes + `--profile`, version-as-ticket fix,
`mcp<2` pin, hermetic tests (0.6.1); `doctor` locks/temp objects/identity,
`gitdir` in `list` (0.6.2); `sync` → `reset`, `merged` in `list`, MCP
`remove` `dry_run`, empty folders cleaned (0.7.0); `grove` alias, `adopt`
alias, `setup` → `convert` hint, version and CLI equivalents in the MCP (0.7.1); `ahead`/`behind` vs base,
`kind: base` (protected), correct paths from another mount — no more false
orphans for `doctor` (0.8.0); neutral cwd for global git config, base
suggestions in `create`/`setup`, CI on 3.11–3.14 (0.8.1); `unset` falls back to the repo's profile, docs:
recipes, configuration, SSH key selection, release process (0.8.2); `gwt fetch`
(0.8.3); `cli/main.py` split into `cli/commands/*` (0.8.4); mcp 2.x, default profile for
repos without `grove.toml`, end-to-end MCP test (0.9.0); structured MCP
results (0.9.1); `gwt start` / `grove_start`, `--no-track` for new branches
(0.9.2); no parking branch — bare `HEAD` → base, `doctor` migration (0.10.0); opt-in `relative_worktrees` (0.11.0); typed MCP output schemas for the
everyday tools + output contract test (0.11.1); typed schemas for all 20 tools
(0.11.2); Agent Skill `skills/grove` + `gwt skill install` (0.12.0); skill feedback —
`skill-outdated` in `doctor`, `gwt repos`, flow for a moved base, Spanish
triggers, first-push troubleshooting (0.13.0); `repos` agrees with `config`,
skill review follow-ups (0.13.1); `skill install` refreshes untouched copies (0.13.2).
