# Specification — Git Worktree management tool (`gwt`)

> Design document. Defines the agreed behavior before coding.
> Status: draft for review. Date: 2026-06-23.

## 1. Goal and scope

Impose a **consistent policy** on how git worktrees are created, named and located across repos, and expose a **queryable inventory** of which worktree corresponds to which ticket/branch.

The real problem is not running `git worktree` (it's four commands), but **drift**: mixed naming, tickets misaligned between folder and branch, accumulated orphan worktrees, and inconsistent `release` formats. The tool encapsulates the convention so that this drift does not occur.

**Architecture decision.** All the logic lives in a reusable **core** (parsing `git worktree`, applying the convention, validations). Thin facades are mounted on top:

- **Phase 1 — CLI** (`gwt`): for manual use and in CI. It is the facade this document specifies.
- **Phase 2 — MCP** (future): the same logic exposed as tools so an agent can orchestrate worktree operations. It is added when needed; it's a few extra lines on top of the same core.

### Design principles

**grove does not query ticket management systems (Jira, Linear, GitHub Issues, etc.) nor any external platform.** All ticket-related information, descriptions or details arrives **by parameter** (or, in phase 2, via the MCP tool that receives it already resolved). grove only needs the *key* and the *slug*; obtaining them is the responsibility of the caller. Reasons:

1. **Single responsibility.** grove's domain is the lifecycle of worktrees and the git convention. Ticket systems are another domain; integrating them would burden grove with API clients, authentication, tokens, rate limits and network failure handling foreign to its purpose.
2. **Pure, offline and deterministic core.** No network or credentials in the core: simpler, safer and reproducible behavior. This keeps the conformance suite as **pure git**, with no need to mock external services.
3. **Platform agnostic.** By not querying anyone, grove works the same with Jira, Linear, GitHub Issues or no system at all. The only thing the convention needs is the key/slug, which the caller provides.
4. **Parity between languages.** If grove queried a platform, each implementation (Python/Go/Rust) would have to reimplement that client → duplication and divergence. By-parameter, the three stay thin and the spec remains a verifiable contract.
5. **Integration at the orchestration layer.** "Functional core, imperative shell" pattern (ports & adapters): grove is the pure core; the network effect (fetching the ticket) is done by the shell — a script or the agent via MCP, which composes "fetch the issue" + "call grove with the data already resolved".

Two corollaries that follow from the above:

- **The name/slug is provided by the caller.** grove only normalizes that name to the convention format and validates it; it never derives it from a free-form description nor from an external source. (See §4.1.)
- **`allowed_types` governs what grove *creates*, not what it can *accommodate*.** `create` restricts the types of new branches; `track` accommodates branches that already exist even if their type is not in `allowed_types` (with a warning). `doctor` reports those deviations but does not force changes on branches the user did not create. (See §6.5 and §6.7.)

## 2. Repository model

Each repo is mounted with the **bare model**: a bare repository in `.bare/` and all worktrees as sibling folders inside the repo folder.

So that the `.bare` does not retain ("occupy") any real branch of the origin, its `HEAD` points to a local parking branch called **`worktree-config-root`**, created locally from `production`. This way `production` stays free to be used by its own worktree and no origin branch is blocked by the bare.

## 3. Directory structure

```
<repo>/
├── .bare/                         # bare repository; HEAD -> worktree-config-root
├── production/                    # SPECIAL: worktree of the production branch
├── temporary-unified-test/        # SPECIAL: unified test branch
├── temp/                          # SPECIAL: container for ephemeral worktrees / ticketless experiments
│   ├── prueba-perf/               #   -> ephemeral branch temp/prueba-perf
│   └── spike-redis/               #   -> ephemeral branch temp/spike-redis
├── artifacts/                     # LOCAL docs/artifacts (NOT a worktree; not versioned or pushed)
├── feature/                       # TYPE
│   ├── PROJ-21114-devolutions-code-review/
│   └── PROJ-18118-endpoint-bf-v2/
├── hotfix/                        # TYPE
│   └── PROJ-23179-fix-order-not-found/
├── bugfix/                        # TYPE
│   └── PROJ-23243-fix-devolution-ownership/
└── release/                       # TYPE (versions hang here)
    └── v1.1.0/                    #   -> branch release/v1.1.0
```

Structure rules:

- The **special** folders (`production`, `temporary-unified-test`, `temp`) and the **type** folders (`feature`, `hotfix`, `bugfix`, `release`) all live at the **same level** inside the repo.
- **Ticket** worktrees always stay **inside** their type folder.
- **Folder ↔ branch coherence:** the relative path of the worktree folder equals the branch name. Example: folder `feature/PROJ-21114-...` ↔ branch `feature/PROJ-21114-...`.

## 4. Naming convention

### 4.1 Ticket worktrees

- **Folder:** `<type>/PROJ-XXXXX-<slug>`
- **Branch:** `<type>/PROJ-XXXXX-<slug>` (identical to the folder path)
- `<type>` ∈ `{ feature, hotfix, bugfix }` (see release separately).
- `PROJ-XXXXX` is the ticket key (Jira style; any platform).
- `<slug>` is the **name provided by the caller**, normalized to the convention format.

**The name/slug is provided by whoever invokes, not grove.** The caller gives the name (its *content* / meaning); grove only **mechanically normalizes** it to the convention format (lowercase, spaces → `-`, no accents or special characters) and **validates** it (not empty). grove does not summarize or derive the content from a free-form description: normalizing the format is enforcing the convention (grove's job), not generating information.

**Key invariant:** the ticket that appears in the folder must be the same as the branch's. The tool **rejects** them differing (this avoids the real case `PROJ-22292-ajustes-ecom` → branch `hotfix/PROJ-22467-...`).

### 4.2 Release

- **Folder:** `release/<version>` (e.g. `release/v1.1.0`)
- **Branch:** `release/<version>`
- Single format with `slash` (`release/vX.Y.Z`). The old dash format (`release-v1.1.0`) is removed.

### 4.3 Special

| Folder | Branch | Notes |
|---|---|---|
| `production` | `production` | Follows `origin/production`. |
| `temporary-unified-test` | `temporary-unified-test` | Test integration branch. |
| `temp/<name>` | `temp/<name>` | Local **ephemeral** branch with the same name. |

## 5. Branch types and base rules

Fixed set of allowed types: **`feature`, `hotfix`, `bugfix`, `release`**. Any other type is rejected. (Adding `chore`/`docs` in the future = one line in the configuration.)

**Default base:** all types branch from **`production`** if `--base` is not passed.

**`release` exception:** see §6.3.

## 6. Commands

Binary name: `gwt`. General convention: `gwt <command> [args] [flags]`.

### 6.1 `gwt setup <url>`

Initializes a new repo with the bare structure.

Steps:

1. `git clone --bare <url> .bare` and configure the refspec so that **all** origin branches are visible (`+refs/heads/*:refs/remotes/origin/*`).
2. Create the `production/` worktree following `origin/production`.
3. Create the local branch `worktree-config-root` based on `production` and point the `.bare`'s `HEAD` to it.

Result: repo ready with `.bare/` + `production/`.

**SSH alias.** The canonical URL copied from the remote does not carry local aliases. `setup` uses it as-is by default, but if `~/.ssh/config` has aliases whose `HostName` matches the URL's host, it detects them and lets you choose (interactive, or `--ssh-alias <alias>`; `none` forces the canonical one). When choosing an alias, it rewrites the `origin` URL to that alias so git uses the correct key in all commands.

The `production/` worktree must end up **tracking** `origin/production` (upstream set and verified; see §6.8).

### 6.2 `gwt create <PROJ-XXXXX> <type> <name> [--base <branch>]`

Creates a **new** ticket worktree.

- `<type>` ∈ `allowed_types` (default from the profile; e.g. `feature`, `hotfix`, `bugfix`).
- `<name>` is provided by the caller; grove **normalizes** it to slug format (it does not derive or summarize it).
- Folder and branch: `<type>/PROJ-XXXXX-<slug>`.
- Base: `--base` if passed, otherwise the repo's base branch.
- **Validations (and all report the reason for failure):** allowed type; folder ticket = branch ticket; **the branch does not already exist** (neither local nor in origin); the destination folder is free; the normalized name is not empty.
- If the branch **already exists**, `create` fails with a reason and suggests **`gwt track <branch>`** (which creates the worktree deriving the name from the existing branch).
- **Upstream:** being a **new** branch, it is not tracked to the base; the upstream stays unset until the first `git push -u` (configure `push.default = current`).

Example:

```
gwt create PROJ-23243 bugfix "fix devolution ownership"
# -> folder bugfix/PROJ-23243-fix-devolution-ownership/
# -> branch bugfix/PROJ-23243-fix-devolution-ownership (base production)
```

### 6.3 `gwt create release <version> [--base <branch>]`

Creates or fetches a release version. The `<version>` is **mandatory**.

Decision tree:

1. Validate that `<version>` **does not collide** with a `release/*` already existing in the origin (when creating a new one).
2. If `release/<version>` **already exists** in the origin → fetches that version: the worktree's local branch ends up **tracking** `origin/release/<version>` (see §6.8).
3. If it **does not exist** → creates the new branch `release/<version>`, with base:
   - the one from `--base` if specified, or
   - **`production`** by default.
   - Being new, no upstream until the first `push -u`.

Example:

```
gwt create release v1.2.0
# v1.2.0 does not exist in origin -> creates release/v1.2.0 from production
```

### 6.4 `gwt create temp <name>`

Creates an ephemeral worktree without a ticket, for experiments.

- Folder: `temp/<name>`.
- Branch: **ephemeral** `temp/<name>` (local, same name).
- They are considered **disposable**: `doctor` may delete them during cleanup without treating them as a loss.

### 6.5 `gwt track <branch> [--as <type>/PROJ-XXXXX-slug]`

Fetches a branch **that already exists** (local or in the origin) and places it in the structure. **The name is derived from the branch** (no slug is passed). `track` *accommodates* what exists, so it is more permissive than `create`.

- Accepts **origin** and **local** branches (local ones without an origin upstream end up untracked).
- Without `--as`: derives the path from the branch name and creates the worktree mirroring that name.
- **Permissive with the type:** if the branch is structurally valid (`<segment>/<key>-<slug>`, or special/temp/release) but its `<segment>` **is not in `allowed_types`** (e.g. `chore/PROJ-12345-limpieza`), grove **fetches it anyway** and emits a **warning** (not an error) indicating that that type is not in `allowed_types`. Reason: the branch already exists; `allowed_types` only restricts what `create` *manufactures*, not what `track` can *accommodate*.
- If the branch **is not structurally parseable** and `--as` is **not** passed → **error** with reason, asking for the destination with `--as`.
- With `--as`: the user explicitly sets the convention destination/name (useful to relocate a non-conventional branch or force an allowed type).
- **Upstream:** if the branch exists in the origin, the local branch ends up **tracking** it (set and verified, see §6.8). If it is only local, no upstream.

Examples:

```
gwt track feature/PROJ-21114-refactor          # origin or local; name derived from the branch

gwt track chore/PROJ-12345-limpieza-comentarios
# 'chore' is not in allowed_types -> WARNING, but it is fetched into chore/PROJ-12345-limpieza-comentarios/

gwt track arreglo-rapido --as hotfix/PROJ-23300-fix-rapido
# non-parseable branch -> placed where --as indicates
```

### 6.6 `gwt list`

Shows the repo's worktree inventory. Columns:

| Column | Content |
|---|---|
| Folder | Relative path of the worktree inside the repo |
| Branch | Associated branch |
| Ticket | `PROJ-XXXXX` extracted (or empty for special/temp) |
| Git status | ahead/behind relative to upstream + clean/dirty |

`list` reports only what git knows; it does not query ticket systems (see Design principles). Any enrichment (issue/PR status) is done by the orchestration layer combining `list` with its own sources.

### 6.7 `gwt doctor`

Detects **and fixes** hygiene problems.

**Fixes automatically** (with confirmation or `--fix`):

- **Orphans:** worktree records whose directory no longer exists → `git worktree prune`.
- **Flat folder of an allowed type:** a folder whose branch *is* of a type in `allowed_types` but which is not under its type folder → moves it to the convention.
- **Old release format:** `release-vX.Y.Z` (dash) → normalizes to `release/vX.Y.Z`.
- **Incorrect or missing upstream:** worktrees fetched from the origin whose local branch does not track —or tracks wrongly— its origin branch → fixes with `git branch --set-upstream-to`.

**Reports but does NOT fix** (requires human judgment):

- **Type not in `allowed_types`:** a well-formed worktree (`<segment>/<key>-<slug>`) whose `<segment>` is not in `allowed_types` (e.g. `chore/PROJ-12345-...`, typically brought in with `track`). It **warns** that it does not adhere to the configuration, **without** moving or renaming it — grove does not force changes on branches the user did not create. (Consistent with the permissiveness of `track`, §6.5.)
- **Folder ticket ≠ branch ticket:** flags the mismatch.
- **Nested worktrees** inside another worktree: flags for relocation.

Behavior: by default it shows the plan and asks for confirmation; `--fix` applies the automatic fixes, `--dry-run` only reports. The "reports but does not fix" items are never touched automatically, not even with `--fix`.

### 6.8 Tracking / upstream (cross-cutting rule)

Every branch that **comes** from the origin must end up with its **upstream explicitly set** to the corresponding remote branch, and the tool **verifies** it after creating the worktree.

Applies to:

- `setup` → `production` tracks `origin/production`.
- `track <branch>` → the local branch tracks `origin/<branch>` (or the one indicated by `--as`).
- `create release <version>` when the version **already exists** in the origin → tracks `origin/release/<version>`.

Mechanics:

- When adding the worktree from a remote branch, set the upstream explicitly (equivalent to `git branch --set-upstream-to=origin/<branch> <branch>`), without relying only on the DWIM of `git worktree add`.
- **Post-creation verification:** confirm with `git rev-parse --abbrev-ref <branch>@{upstream}` that the upstream points to the expected origin branch; if not, abort/repair.

Does not apply (**new** branches: `create` feature/hotfix/bugfix, and a new `release`): upstream is not set to `production`; the upstream is established at the first `git push -u`. `push.default = current` is configured so that this first push creates the same-named branch in the origin.

### 6.9 `gwt ssh check [<url-or-host>] [--all] [--live]`

Diagnoses the SSH configuration relevant to authenticate against git remotes. Useful when several remotes/accounts (work and personal) coexist with different keys. It is **read-only**: it never modifies `~/.ssh/config`.

Unlike the rest, it **does not require** being inside a managed repo.

> **Read vs write.** `ssh check` is the **read-only** diagnostic of low-level connectivity. The **write-mode** account provisioning (`ssh add`, `ssh accounts`, `ssh doctor`, `ssh remove`) is specified in **§14**; it is what creates and repairs the multi-account setup that `check` merely inspects.

- **Contextual (default):** takes the host from the current repo's `origin`, or from the `<url-or-host>` passed. If there is no repo or argument → asks for a URL or `--all`.
- **`--all`:** enumerates all `Host` entries in `~/.ssh/config` and reports each one.
- **`--live`:** additionally runs `ssh -T` (with timeout) against the host and interprets the authentication response. Without `--live` there is no network traffic.

What it reports (style `✓ ! ✗`):

- Applicable `Host` block, `HostName`, `User`, `IdentityFile`, `IdentitiesOnly`.
- Whether the key(s) exist and have correct permissions (`600`; on Windows it is marked N/A).
- Whether the `ssh-agent` is running and whether the resolved identity is loaded.
- With `--live`: authentication result (GitHub/Bitbucket return a recognizable success message even if the exit code is ≠ 0).

Implementation: config resolution uses `ssh -G <host>` (lets ssh itself resolve `Include`, `Match` and wildcards); manual parsing of `~/.ssh/config` is reserved only for enumerating `Host` entries in `--all` mode.

**Without `~/.ssh/config`:** contextual mode works the same (`ssh -G` uses the defaults) and shows only the keys that exist, warning of the absence of config. In `--all`, with no `Host` to enumerate, grove offers an alternative overview: keys present in `~/.ssh`, agent status, and diagnosis of known git hosts (`known_git_hosts`, configurable; by default `github.com`, `bitbucket.org`, `gitlab.com`).

### 6.10 `gwt remove <target> [--delete-branch] [--force] [--merged] [--dry-run]`

Removes worktrees safely. Alias: `gwt rm`.

- **Target:** resolved by **ticket**, **branch** or **path** (if ambiguous, lists candidates and aborts).
- **By default (safe):** removes the worktree (`git worktree remove`) and **keeps** the local branch.
- **`--delete-branch`:** additionally deletes the local branch, but **only if it is merged into the base or pushed** (upstream with no pending commits); if not, aborts and suggests `--force`.
- **`--force`:** removes even if the worktree is dirty; with `--delete-branch`, deletes the branch even if it is not merged/pushed.
- **`--merged`:** mass sweep — removes all **ticket** worktrees whose branch is merged into the base (combinable with `--delete-branch`). Does not touch special or temp.
- **`--dry-run`:** shows what it would do without executing.

Safeguards: special ones (`production`, `temporary-unified-test`) are protected and never removed with `remove`; a worktree with uncommitted changes requires `--force`.

### 6.11 `gwt sync [<target>] [--clean] [--yes] [--dry-run]`

Re-synchronizes a worktree with the origin's state: `git fetch origin <branch>` + `git reset --hard origin/<branch>`. Intended for branches that are **regenerated/force-pushed** (e.g. the shared test integration branch), where a normal `pull` diverges.

- **Target:** ticket, branch or path; if omitted, uses the current directory's worktree.
- **Destructive:** discards unpushed local commits and uncommitted changes. If there are any, it warns what will be lost and asks for confirmation; `--yes` skips it.
- **`--clean`:** additionally runs `git clean -fd` (deletes untracked files).
- **`--dry-run`:** shows what it would do without executing.

> Note: `track` recognizes special branches (`production`, `temporary-unified-test`, `development`, ...) and `temp/*`, placing them in their convention path; this way the integration branch can be fetched and then `sync`ed.

### 6.12 `gwt publish <ticket|branch>... [--into <branch>] [--regenerate] [--base <branch>] [--no-sync] [--yes] [--dry-run]`

Brings one or more ticket branches to the **shared integration branch** (config `integration_branch`, by default `temporary-unified-test`; override with `--into`). If that branch is not present as a local worktree, grove fetches it from the origin automatically.

**Additive mode (default):**
1. Synchronizes the integration branch with the origin (unless `--no-sync`).
2. `merge`s each indicated branch/ticket.
3. `push`es to `origin/<integration>`.

**Regeneration mode (`--regenerate`):**
1. Resets the integration branch to `origin/<base>` (`--base`, by default the repo's base).
2. `merge`s the branches/tickets in order.
3. `push --force` to `origin/<integration>` (with confirmation, unless `--yes`).

In both modes, a merge **conflict** aborts the operation (leaves the worktree clean) and asks to resolve by hand. `--dry-run` shows the steps without executing.

### 6.13 `gwt config [show | set-ssh-alias <alias|none>]`

Shows or adjusts the repo configuration (`.bare/grove.toml`).

- **`show`** (default): reports the repo, `origin` and the effective policy; with `--json`, as a parseable object.
- **`set-ssh-alias <alias>`**: saves `ssh_alias` in the config and rewrites the `origin` to the alias (so git uses the correct key); `none` resolves the real host and reverts to the canonical URL.

The alias chosen in `setup` (§6.1) is persisted in `ssh_alias`, and this command lets you query or change it later.

### 6.14 `gwt artifacts [<worktree>]`

Prints (and creates if missing) the path of the repo's **local artifacts/documentation folder** (`artifacts/` by default; configurable with `artifacts_dir`, `""` disables it).

- It is a **flat folder at the repo level, outside any worktree**: since it does not belong to any branch's tree, it is **never versioned or pushed** to the remote. It is the structural guarantee (does not depend on `.gitignore`). `list`/`doctor`/`remove` ignore it because it is not a worktree.
- Without argument → path of `artifacts/` (bare, for `cd "$(gwt artifacts)"` or so a skill knows where to write).
- With `<worktree>` → path of a subfolder `artifacts/<name>` (if the argument resolves to a worktree, uses its name; if not, a slug of the text). Useful to associate artifacts with a specific piece of work.
- `setup` creates the folder upon initialization.

It is not versioned, so it has no history; if history is wanted, it is the user's responsibility (e.g. a git of their own inside that folder).

### 6.15 `gwt compare [<a>] [<b>] [--vs <ref>] [--fetch]`

**Read-only.** Shows the synchronization state (ahead/behind) between branches/worktrees, with `git rev-list --left-right --count a...b`.

- **No arguments:** the current worktree (according to the directory) vs **its upstream**.
- **`<a>`:** that worktree/branch vs its upstream.
- **`<a> <b>`:** compares `a` vs `b`.
- **`--vs <ref>`:** compares **all** worktrees against `ref` (overview table).
- **`--fetch`:** does `git fetch` first (the only action that touches the network; without it, uses what is already there).

Each side is resolved flexibly: if the token matches a worktree (ticket/branch/path) it uses its branch; if not, it is treated as a git ref (`main`, `origin/main`, a SHA). It reports `↑ahead ↓behind` and a status: *in sync* / *ahead* / *behind* / *diverged*. With `--json`, structured.

### 6.16 `gwt patch [<worktree>] [--base <ref>] [--format-patch] [--wip] [--output <path>] [--stdout]`

Generates a patch of the worktree to **share or back up without pushing**.

- **Target:** current worktree by default, or the one indicated.
- **Default:** combined diff of the branch's contribution vs its base (`git diff <base>...HEAD`), a single file applicable with `git apply`.
- **`--format-patch`:** one `.patch` per commit (`git format-patch <base>..HEAD`), applicable with `git am`; goes to its own subfolder per invocation.
- **`--wip`:** the **uncommitted** changes (working tree vs HEAD), to back up half-done work.
- **`--base <ref>`:** comparison base (default: the repo's base branch).
- **Output:** by default in `<artifacts>/patches/`, named `<branch>__<datetime>.diff` (or a subfolder for `--format-patch`). `--output <path>` sets it; `--stdout` prints it without writing a file. If `artifacts_dir` is disabled and no `--output`/`--stdout` is given, it falls back to the current directory.

It fits with the local artifacts folder (§6.14): patches are kept locally and are not versioned or pushed.

## 7. Cross-cutting validations

- Branch type within the allowed set.
- Folder ticket = branch ticket in ticket worktrees.
- Do not create branches/folders that already exist.
- `release`: mandatory version and no collision with the origin.
- Protected special ones: `production`, `temporary-unified-test` are never deleted automatically; `temp/*` is disposable.

## 8. Per-repo configuration and profiles

grove is **remote agnostic at the repo level**: in `setup <url>` whatever URL is given is cloned (work or personal); deciding which key authenticates a given repo belongs to git + SSH (`~/.ssh/config`), not to the per-repo policy. What changes between contexts is the **policy**, and that is why it is configurable per repo.

> **Scope clarification (see §14).** "Per-repo remote handling is not grove's job" remains true. What §14 adds is a separate, machine-level capability: **provisioning and repairing the `~/.ssh/config` + `~/.gitconfig` multi-account setup** itself. That is a different domain (the developer's machine, not a repo) and is explicitly opt-in via the `gwt ssh` write commands. The per-repo core stays remote-agnostic.

### 8.1 Configuration resolution (precedence)

From lowest to highest priority:

1. grove's internal defaults.
2. User global config (`~/.config/grove/config.toml`), where the **profiles** are defined.
3. Repo config (`.bare/grove.toml`), which `setup` writes upon initialization.
4. Environment variables (e.g. `GROVE_TICKET_PREFIX`).
5. CLI flags.

This way a work repo and a personal one coexist on the same machine with different policies without having to remember to export anything.

### 8.2 Configurable fields (`.bare/grove.toml`)

```toml
parking_branch = "worktree-config-root"   # normally global, does not change
default_base    = "production"             # e.g. "main" in personal repos
allowed_types   = ["feature", "hotfix", "bugfix", "release"]
special_worktrees = ["production", "temporary-unified-test"]
temp_dir        = "temp"

tickets         = "required"               # required | optional | off
ticket_prefixes = ["DROP", "OPS"]          # accepted keys (recommended)
# ticket_pattern  = "DROP-\\d+"            # alternative: explicit regex (takes priority)

[release]
format       = "release/{version}"         # slash, not dash
default_base = "production"
```

### 8.3 Ticket policy

The `tickets` field defines how ticket worktrees are named and has three modes:

- **`required`**: requires a key (`gwt create DROP-123 feature "..."` → `feature/DROP-123-...`).
- **`off`**: no key, only description (`gwt create feature "..."` → `feature/...`).
- **`optional`**: accepts both; if the first argument matches the ticket pattern it is used as a ticket, if not, slug mode.

Cascading effects depending on the mode: in `off`/no key, the TICKET column of `list` stays empty, the invariant "folder ticket = branch ticket" does not apply, and `doctor` does not report ticket mismatches.

**What counts as a ticket** is defined by the pattern, configurable in three ways (from highest to lowest priority): the env `GROVE_TICKET_PREFIX` (one or several keys separated by comma/space), `ticket_pattern` (explicit regex), or `ticket_prefixes` (list of keys, the recommended form; grove converts it into `(?:DROP|OPS)-\d+`). Unconfigured, the generic pattern accepts any Jira-style key. The pattern is used in `create` (validate/detect), `track` (parse), `list` (TICKET column), `doctor` (folder≠branch) and when resolving targets by ticket in `remove`/`publish`.

### 8.4 Profiles (global config)

grove ships with built-in profiles (`default`, `personal`, `gitflow`). To avoid configuring each repo by hand, the global config can add or override profiles that `setup --profile <name>` materializes in the repo's `grove.toml`. Example of a custom work profile with required tickets and an integration branch:

```toml
[profiles.work]
default_base = "production"
allowed_types = ["feature", "hotfix", "bugfix", "release"]
special_worktrees = ["production", "qa-integration"]
tickets = "required"
ticket_prefixes = ["PROJ"]
integration_branch = "qa-integration"
```

This allows starting a personal repo at `tickets = optional` with simple types and, when a ticket system is adopted, bumping it to `required` without redoing what exists: the tool accompanies the evolution toward better-structured repos.

## 9. Appendix — Inconsistencies detected in the current state

Diagnosis that motivated this tool (8 repos, all with worktrees):

1. **Two structural models mixed:** 3 repos in the bare model (`repo-A`, `repo-B`, `repo-C`) and 5 in the non-bare `config-root` model (`repo-D`, `repo-E`, `repo-F`, `repo-G`, `repo-H`).
2. **Orphan worktrees:** in `repo-D`, records at the workspace root (`PROJ-22292-ajustes-ecom`, `PROJ-22646-...`, `PROJ-22660-...`) that no longer exist on disk.
3. **Folder with a ticket different from its branch's:** `PROJ-22292-ajustes-ecom` → branch `hotfix/PROJ-22467-...`.
4. **Mixed folder naming:** some flat (`PROJ-21114-...`), others nested under the type (`hotfix/PROJ-22930-...`).
5. **Inconsistent branch type:** the same ticket `PROJ-20341` in several worktrees with `hotfix/` and `bugfix/` prefixes; refactors labeled sometimes `hotfix/`, sometimes `feature/`.
6. **`release` in two formats:** `release/v1.1.6` (slash) vs `release-v1.1.0` (dash).
7. **Worktree nested inside another:** `repo-E/release-v1.1.0/PROJ-20341-log-create-products-errors` (also orphan).

The tool prevents 2–7 by design and fixes them via `gwt doctor`.

## 10. Command-line interface (flags and messages)

### 10.1 Global conventions

General form: `gwt <command> [arguments] [flags]`.

**Context detection.** Except for `setup`, all commands require running inside a managed repo: the tool searches for `.bare/` upward from the current directory. If it does not find it → usage error.

**Global flags:**

| Flag | Effect |
|---|---|
| `-h, --help` | Command help |
| `--version` | `gwt` version |
| `-q, --quiet` | Only warnings and errors (suppresses `→` and `✓`) |
| `-v, --verbose` | Prints each git command executed, step by step, before running it |
| `--confirm-each` | Step-through mode: shows each git command and asks for confirmation before executing it (implies `-v`) |
| `--json` | JSON output (applies to `list` and `doctor`) |
| `--no-color` | No colors |
| `-C <path>` | Runs as if the cwd were `<path>` (same as `git -C`) |

**Message style:**

- `→` step/action in progress
- `✓` success (green)
- `!` warning (yellow)
- `✗` error (red, to `stderr`)

**Exit codes:** `0` success · `1` validation/convention error · `2` git error · `3` incorrect usage (args/flags).

**JSON output (`--json`, global).** Since exit codes alone lend themselves to interpretation, `--json` emits a single object with `status` (`ok`/`error`), `exit_code`, `message` (the human-readable reason), `error_type` (on errors), `result` (structured data depending on the command) and `log` (the steps). In `--json` mode there is no other output or interactive confirmations: destructive operations require `--yes`/`--force` or return an error explaining it.

**Verbose mode.** With `-v/--verbose`, each underlying git command is printed with a `$` prefix right before running, interspersed with the `→` steps. This way you see exactly what the tool does. Example (`setup`):

```
$ gwt setup git@github.com:acme/myrepo.git -v
→ Cloning bare into myrepo/.bare
  $ git clone --bare git@github.com:acme/myrepo.git myrepo/.bare
→ Configuring origin refspec
  $ git -C myrepo/.bare config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
  $ git -C myrepo/.bare fetch origin
→ Creating worktree production/ (origin/production)
  $ git -C myrepo/.bare worktree add ../production production
  $ git -C myrepo/production branch --set-upstream-to=origin/production production
→ Creating parking branch worktree-config-root (base production)
  $ git -C myrepo/.bare branch worktree-config-root production
  $ git -C myrepo/.bare symbolic-ref HEAD refs/heads/worktree-config-root
✓ Repo myrepo ready
```

(The git commands shown are illustrative of the flow; the exact ones are fixed in the implementation.)

For specific cases, `--confirm-each` activates a step-through mode: it shows each git command and waits for confirmation (`[y/N]`) before executing it. Implies `-v`. It is not for normal use; it serves when you want to validate a delicate operation step by step.

### 10.2 `gwt setup`

```
gwt setup <url> [--name <dir>] [--into <path>]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<url>` | — (mandatory) | Origin URL |
| `--name <dir>` | basename of the url without `.git` | Name of the repo folder |
| `--into <path>` | cwd | Where to create the repo folder |

```
$ gwt setup git@github.com:acme/myrepo.git
→ Cloning bare into myrepo/.bare
→ Configuring origin refspec (+refs/heads/*:refs/remotes/origin/*)
→ Creating worktree production/ (origin/production)
→ Creating parking branch worktree-config-root (base production)
→ bare HEAD -> worktree-config-root
✓ Repo myrepo ready
  .bare/       bare repository
  production/  production  [tracks origin/production]
```

### 10.3 `gwt create` (ticket)

```
gwt create <PROJ-ID> <feature|hotfix|bugfix> "<name>" [--base <branch>] [--print-path] [--dry-run]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<PROJ-ID>` | — | Ticket key (`PROJ-XXXXX`, any platform) |
| `<type>` | — | `feature` \| `hotfix` \| `bugfix` |
| `"<name>"` | — | Source of the slug |
| `--base <branch>` | `production` | Base branch |
| `--print-path` | — | Prints only the created path (for `cd "$(gwt create ... --print-path)"`) |
| `--dry-run` | — | Shows what it would do without executing |

```
$ gwt create PROJ-23243 bugfix "fix devolution ownership"
→ slug: fix-devolution-ownership
→ Validating: type bugfix ✓ · ticket folder=branch ✓ · branch free ✓
→ Creating worktree bugfix/PROJ-23243-fix-devolution-ownership/ (base production)
✓ Worktree created
  folder    bugfix/PROJ-23243-fix-devolution-ownership
  branch    bugfix/PROJ-23243-fix-devolution-ownership
  base      production
  upstream  (unset — when done: git push -u)
```

```
$ gwt create PROJ-23243 chore "limpieza"
✗ Type 'chore' not allowed. Valid types: feature, hotfix, bugfix.
```

### 10.4 `gwt create release`

```
gwt create release <version> [--base <branch>]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<version>` | — (mandatory) | Version, e.g. `v1.2.0` |
| `--base <branch>` | `production` (only if new) | Base of a new release |

```
$ gwt create release v1.2.0
→ Checking collision: origin does not have release/v1.2.0 ✓
→ Creating new branch release/v1.2.0 (base production)
→ Creating worktree release/v1.2.0/
✓ Release v1.2.0 created (new)
```

```
$ gwt create release v1.1.0
→ origin/release/v1.1.0 exists -> fetching existing version
→ Creating worktree release/v1.1.0/ tracking origin/release/v1.1.0
→ Verifying upstream -> origin/release/v1.1.0 ✓
✓ Release v1.1.0 fetched from origin
```

### 10.5 `gwt create temp`

```
gwt create temp <name>
```

```
$ gwt create temp spike-redis
→ Creating worktree temp/spike-redis/ with ephemeral branch temp/spike-redis (base production)
! Ephemeral worktree: doctor may delete it during cleanup.
✓ Ready: temp/spike-redis
```

### 10.6 `gwt track`

```
gwt track <origin-branch> [--as <type>/PROJ-XXXXX-slug]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<origin-branch>` | — | Exact name of the branch in the origin |
| `--as <path>` | parsed from the name | Explicit destination when the branch does not meet the convention |

```
$ gwt track feature/PROJ-21114-refactor-devolutions-ecom-scanner
→ origin/feature/PROJ-21114-refactor-devolutions-ecom-scanner found
→ Parsed: type=feature · ticket=PROJ-21114 · slug=refactor-devolutions-ecom-scanner
→ Creating worktree feature/PROJ-21114-refactor-devolutions-ecom-scanner/
→ Setting upstream -> origin/feature/PROJ-21114-refactor-devolutions-ecom-scanner
→ Verifying upstream ✓
✓ Branch fetched and tracking origin
```

```
$ gwt track arreglo-rapido
✗ 'arreglo-rapido' does not meet the convention (<type>/PROJ-XXXXX-slug).
  Indicate the destination with --as, for example:
    gwt track arreglo-rapido --as hotfix/PROJ-23300-fix-rapido
```

### 10.7 `gwt list`

```
gwt list [--type <type>] [--dirty] [--orphans] [--json]
```

| Flag | Description |
|---|---|
| `--type <type>` | Filters by type (`feature`/`hotfix`/`bugfix`/`release`/`temp`/`special`) |
| `--dirty` | Only worktrees with uncommitted changes |
| `--orphans` | Only orphan records |
| `--json` | JSON output |

```
$ gwt list
FOLDER                                        BRANCH                                        TICKET      STATUS
production                                    production                                    —           ↑0 ↓0 clean
feature/PROJ-21114-refactor-devolutions-...   feature/PROJ-21114-refactor-devolutions-...   PROJ-21114  ↑2 ↓0 dirty
release/v1.1.0                                release/v1.1.0                                —           ↑0 ↓1 clean
temp/spike-redis                              temp/spike-redis                              —           ↑1 ↓0 clean
```

### 10.8 `gwt doctor`

```
gwt doctor [--fix] [--dry-run] [--json]
```

| Flag | Behavior |
|---|---|
| (no flag) | Reports and, if there are automatic fixes, asks for interactive confirmation |
| `--fix` | Applies the fixes without asking (for CI) |
| `--dry-run` | Only reports, never modifies |
| `--json` | Report in JSON |

```
$ gwt doctor
→ Analyzing worktrees of myrepo
Problems found:
  ✗ orphan    PROJ-22292-ajustes-ecom       record without directory             -> prune
  ✗ naming    PROJ-21114-devolutions-...    flat folder, should go in feature/    -> move
  ✗ release   release-v1.1.0                dash format                           -> rename to release/v1.1.0
  ✗ upstream  release/v1.1.0                no upstream                           -> set-upstream origin/release/v1.1.0
  ! ticket    PROJ-22292-ajustes-ecom -> branch hotfix/PROJ-22467-...  (folder≠branch)  review manually
3 fixable automatically · 1 requires manual review.
Apply the 3 fixes? [y/N]
```

## 11. Implementation decisions

- **Language: Python**, standard library only (no pip dependencies). Reasons: robust parsing of `git worktree --porcelain`, regex (`PROJ-XXXXX`), safe handling of paths with accents, native `json` for `--json`, and —key— that the **core be importable by the MCP facade** of phase 2.
- **Architecture: separate core + CLI.** The core contains the logic (convention, validations, git wrappers); the CLI is a thin facade. Phase 2 (MCP) reuses the same core.
- **Cross-platform (incl. Windows):** use `pathlib` and stdlib throughout; never concatenate paths with `/` by hand. ASCII-safe slugs (valid in NTFS). ANSI colors with support detection and respect for `--no-color`/`NO_COLOR`.
- **Distribution: installable package with an entry point** (`pipx install`), which creates the `gwt` executable identical on Windows/mac/Linux. Emergency exits on Windows: Git Bash or WSL.

## 12. Pending / next steps

- **Align the Python implementation with the refined contract** (pending code deltas):
  - `create`: rename the `description` argument → `name`; the "branch already exists" message should point to `track` (local or remote).
  - `track`: accept **local** branches in addition to the origin; be **permissive** with types outside `allowed_types` (fetch + warn) instead of requiring `--as`; derive the name from the branch.
  - `doctor`: new item **"type not in allowed_types"** that is **reported** (manual) without auto-fix; do not mark as "out of convention" what `track` does accept.
- **(Idea to discuss)** Command to **compare synchronization state between branches**: local worktree vs its remote, or between two worktrees/branches (ahead/behind, divergence), read-only, with optional `--fetch`.
- **(Idea to discuss)** Generate a **patch file on demand** from a worktree (diff vs base/upstream, or `format-patch` of one's own commits) to share/back up without pushing. Possible destination: the local artifacts directory.
- **SSH account provisioning module** (`gwt ssh add | accounts | doctor | remove`) — machine-level multi-account setup specified in **§14**. **Implemented in python 0.4.0** across all six phases: `core/platform` + `core/blockedit` (marker-based idempotent atomic edits), `core/sshprov` (account/zone model + read/add/remove), `core/gitidentity` (zones + global hardening), `core/sshdoctor` (diagnose/fix), the four CLI subcommands extending the `ssh` group, the cross-platform layer (macOS/Linux/Windows, §14.8), and the MCP tools (§14.9). Reuses the existing `sshcheck`/`sshalias` modules for read/resolve. See `docs/DESIGN-ssh-provisioning.md` for the implementation design.
- Test the prototype against real repos and once on Windows before considering it stable.
- **Conformance suite** (black box, language agnostic) to guarantee parity between implementations; detailed plan in `conformance/README.md`. Built when the 2nd implementation appears.
- Implementations in Go and Rust (monorepo: `python/`, `go/`, `rust/`).

Already implemented: per-repo config (`.bare/grove.toml`), profiles (`default`/`personal`/`gitflow` built-in + custom ones in `~/.config/grove/config.toml`), `setup --profile`, the `tickets` policy (off/optional/required) with its effects on `create`/`doctor`/`list`, and the **SSH account provisioning module** of §14 (`gwt ssh add | accounts | doctor | remove`, cross-platform, with MCP tools).

## 13. MCP facade (implemented)

This section describes how grove is exposed as an **MCP** (Model Context Protocol) server so that an agent (Claude/Cowork) invokes its operations. **Implemented** in python 0.3.0 (worktree/config/ssh-check tools) and extended in 0.4.0 with the SSH provisioning tools (§14.9); shipped behind the optional extra `pip install "grove[mcp]"` with the `grove-mcp` entry point.

### 13.1 Principle

The MCP is **another thin facade over `core`**, just like the CLI:

```
core            ← logic (convention, git, validations)
 ├── cli   → gwt command
 └── mcp   → MCP server: the same operations as "tools"
```

Two pieces already built make it almost free:

- The **`--json`** output already produces a structured `result`: it is exactly what an MCP tool returns.
- Destructive operations **do not use interactive prompts** (they require `--yes`/`--force`): an agent confirms by parameter, not by answering `[y/N]`.

### 13.2 Tools

Mapping ≈1:1 with the commands: `grove_setup`, `grove_list`, `grove_create`, `grove_track`, `grove_remove`, `grove_sync`, `grove_publish`, `grove_doctor`, `grove_config`, `grove_ssh_check`, and the account-provisioning tools `grove_ssh_add`, `grove_ssh_accounts`, `grove_ssh_doctor`, `grove_ssh_remove` (§14.9). Differences from the CLI:

- **Typed** inputs (JSON schema) instead of text flags.
- **No interaction**: confirmation of destructive actions goes as a boolean parameter.
- Output always **structured** (the `result`), never human text.
- Each tool carries a **description** that the agent uses to decide when to invoke it.

### 13.3 Enrichment

The added value over the 1:1 is combining grove with external context, but **respecting the design principle**: grove's MCP facade also does not go out to the network. Enrichment is **agent composition**: for example, the agent uses its own Jira/GitHub connector to fetch the title of an issue and then calls `grove_create` with that data already resolved; or annotates the output of `grove_list` with the status of PRs it itself queries. grove exposes the worktree operations receiving the info by parameter; it does not incorporate ticket platform clients.

### 13.4 Fit in the monorepo

The MCP **is not language agnostic** (it imports the core of one implementation), so it **lives inside the language's folder**, not at the root:

```
python/
├── pyproject.toml          # entry points: gwt and grove-mcp; MCP SDK as an OPTIONAL dependency
└── src/grove/
    ├── core/   cli/         # existing
    └── mcp/                 # MCP facade (_ops.py + server.py)
```

- **MCP SDK as an optional extra** (`pip install "grove[mcp]"`), so the base CLI stays dependency-free.
- **Own entry point** `grove-mcp` that launches the server (stdio transport).
- **Versions with the implementation** (`python/vX.Y.Z`).
- If Go/Rust want their own MCP, each would have its own under its folder, reusing its core. The spec remains the common contract; the conformance suite could also validate the MCP layer.

## 14. SSH account provisioning (`gwt ssh add | accounts | doctor | remove`)

A machine-level capability to **set up, inventory, diagnose and tear down** the multi-account SSH + git-identity configuration in a way that is **organized, repeatable and bulletproof** — so the developer never has to doubt how to wire a new account, and the classic failure modes cannot happen by construction.

This complements the read-only `gwt ssh check` (§6.9): `check` *inspects*, the commands here *provision and repair*.

### 14.1 Why it lives in grove (and how it respects the design principles)

- **Offline, deterministic core.** Provisioning shells out to `ssh-keygen` / `ssh-add` (local subprocesses, same pattern as the git wrappers). **It never touches the network.** In particular, grove **does not upload public keys** to GitHub/Bitbucket — it prints the public key and the upload is done by the user, or by the agent composing `grove_ssh_add` with its own hosting connector (the "imperative shell" pattern, §1 and §13.3).
- **No parallel state.** The source of truth is the **canonical files** (`~/.ssh/config`, `~/.gitconfig` and the git config files it `include`s). grove does not keep an accounts registry; it **derives** the inventory by reading those files. To operate safely on them it wraps every block it owns in **sentinel markers** (see §14.3) and never edits anything outside its markers.
- **Idempotent.** Re-running `ssh add` for an existing account updates its block in place; it never duplicates.
- **Cross-platform.** macOS, Linux and Windows are first-class; the differences are isolated in a small platform layer (§14.8).

### 14.2 Model: accounts and zones

Two concepts, each mapping to one of the two independent mechanisms a multi-account setup needs:

- **Account** = the **SSH layer** for one hosting account. Fields: `name` (logical id, also the SSH `Host` alias, e.g. `dropi-gh`), `host` (the real `HostName`, e.g. `github.com`), `key` (private key path, default `~/.ssh/id_ed25519_<name>`). Produces one `Host` block in `~/.ssh/config`.
- **Zone** = the **git-identity layer** for a folder. Fields: `scope_dir` (a directory, e.g. `~/dropi/`), `email` (the git author email for repos under it), and the set of accounts routed within it. Produces one `includeIf "gitdir:<scope_dir>"` in `~/.gitconfig` pointing to a grove-owned identity file that carries the `[user] email` plus the `insteadOf` rewrites (canonical URL → alias) for every account in the zone.

Several accounts can share a zone (e.g. `dropi-gh` and `dropi-bb` both under `~/dropi/`). The relationship is: **zone 1—N accounts**. This is exactly why the identity routing is keyed by folder, not by account.

Why this split is bulletproof: the **folder decides everything**. A canonical clone (`git@github.com:org/repo.git`) made inside a zone is rewritten by `insteadOf` to the account alias (→ correct key) and gets the zone's email (→ correct authorship), with **zero** manual alias typing. See §13 of the companion guide for the end-to-end rationale.

### 14.3 Sentinel markers (how grove edits files safely)

Every region grove manages is delimited so `accounts`/`doctor`/`remove` act only on grove-owned regions and **never clobber hand-written config**:

`~/.ssh/config`:

```sshconfig
# >>> grove:account=dropi-gh >>>
Host dropi-gh
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_dropi_gh
    IdentitiesOnly yes
# <<< grove:account=dropi-gh <<<
```

`~/.gitconfig` (the `includeIf` line is marked; the included file is grove-owned):

```gitconfig
# >>> grove:zone=dropi >>>
[includeIf "gitdir:~/dropi/"]
    path = ~/.config/grove/identities/dropi.gitconfig
# <<< grove:zone=dropi <<<
```

`~/.config/grove/identities/dropi.gitconfig` (fully grove-owned; safe to rewrite):

```gitconfig
[user]
    email = victor.orobio@dropi.co
[url "git@dropi-bb:"]
    insteadOf = git@bitbucket.org:
    insteadOf = https://bitbucket.org/
[url "git@dropi-gh:"]
    insteadOf = git@github.com:
    insteadOf = https://github.com/
```

Unmarked blocks are **read** (to detect conflicts) but **never modified**. On Windows the same markers apply to the same files under `%USERPROFILE%` (§14.8).

### 14.4 `gwt ssh add <name>`

```
gwt ssh add <name> --host <host> --email <email>
                   [--scope-dir <path>] [--key <path>]
                   [--no-identity] [--no-agent] [--no-passphrase]
                   [--print-pubkey] [--dry-run]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<name>` | — | Logical id = SSH alias (must be a valid host token: letters, digits, `-`, `_`) |
| `--host <host>` | — | Real host (`github.com`, `bitbucket.org`, `gitlab.com`, …) |
| `--email <email>` | — | git author email for this account's zone |
| `--scope-dir <path>` | — | Folder that routes this account (defines/joins a zone). If omitted → `--no-identity` is implied (alias-only, no git routing) |
| `--key <path>` | `~/.ssh/id_ed25519_<name>` | Private key path |
| `--no-identity` | — | Configure only the SSH layer; do not touch `~/.gitconfig` |
| `--no-agent` | — | Do not load the key into the agent/keychain |
| `--no-passphrase` | — | Generate the key without passphrase (for headless/CI; interactive prompts a passphrase by default) |
| `--print-pubkey` | — | Print only the public key (for piping to an upload step) |
| `--dry-run` | — | Show the planned file edits without writing |

Steps (all idempotent):

1. **Validate** name/host/email; resolve the key path.
2. **Key:** if the key does not exist → `ssh-keygen -t ed25519 -C "<name>" -f <key>` (prompts passphrase unless `--no-passphrase`). If it exists, reuse it.
3. **SSH block:** upsert the marked `Host <name>` block (`HostName`, `User git`, `IdentityFile`, `IdentitiesOnly yes`).
4. **Identity routing** (unless `--no-identity`): ensure the zone for `--scope-dir` (create the `includeIf` + identity file, or join the existing one), upsert `[user] email` and the `[url …] insteadOf` rewrites mapping the canonical host → this alias. **Harden the global `~/.gitconfig`:** ensure `user.name` is set and `user.useConfigOnly = true` (so git can never auto-invent an identity); if a **conflicting global `insteadOf`** for the same host exists (e.g. a token-bearing rewrite) it is **reported, never auto-removed** (it may contain a secret — human decision).
5. **Agent:** unless `--no-agent`, load the key (macOS `ssh-add --apple-use-keychain`; Linux/Windows plain `ssh-add`; see §14.8).
6. **Output:** print the public key and the **upload instructions** for the host (grove does not upload). Verify with a hint to run `gwt ssh check <host> --live` after uploading.

```
$ gwt ssh add dropi-gh --host github.com --email victor.orobio@dropi.co --scope-dir ~/dropi
→ Generating key ~/.ssh/id_ed25519_dropi_gh (ed25519)
→ Writing ~/.ssh/config block [grove:account=dropi-gh]
→ Zone 'dropi' (~/dropi/): includeIf + identity file
→ Routing git@github.com: → git@dropi-gh:  ·  email victor.orobio@dropi.co
→ Hardening ~/.gitconfig: user.useConfigOnly = true
→ Loading key into agent (keychain)
✓ Account dropi-gh ready
  Upload this public key to GitHub (Settings → SSH keys):
  ssh-ed25519 AAAA... dropi-gh
  Then verify:  gwt ssh check github.com --live
```

### 14.5 `gwt ssh accounts [--json]`

Inventory of grove-managed accounts (derived from the marked blocks). Columns:

| Column | Content |
|---|---|
| Account | Alias / `name` |
| Host | Real `HostName` |
| Key | Path · exists? · in agent? |
| Zone | `scope_dir` and email (or `—` if alias-only) |
| Routing | `✓` if `includeIf` + `insteadOf` are coherent, `!` if partial, `—` if none |

```
$ gwt ssh accounts
ACCOUNT      HOST          KEY                          ZONE                         ROUTING
dropi-gh     github.com    id_ed25519_dropi_gh ✓ agent  ~/dropi/  dropi.co            ✓
dropi-bb     bitbucket.org id_ed25519_dropi_bb ✓ agent  ~/dropi/  dropi.co            ✓
personal-gh  github.com    id_ed25519_personal ✓ agent  ~/personal/  me@example.com   ✓
```

(Distinct from `ssh check --all`, which diagnoses connectivity of *all* `Host` entries; `accounts` lists only what grove manages and its routing coherence.)

### 14.6 `gwt ssh doctor [--fix] [--dry-run] [--json]`

The diagnostic-and-repair engine — it encodes every failure mode documented in the companion guide. Mirrors the worktree `doctor` (§6.7) behavior: by default reports and asks; `--fix` applies safe fixes; `--dry-run` only reports; report-only items are never auto-touched.

**Detects and fixes automatically** (with confirmation or `--fix`):

| Check | Problem | Fix |
|---|---|---|
| Key permissions | Private key not `600` (POSIX only) | `chmod 600` |
| `IdentitiesOnly` | A managed `Host` block lacks `IdentitiesOnly yes` | add it |
| Agent | Managed key not loaded | `ssh-add` (keychain on macOS) |
| `useConfigOnly` | `user.useConfigOnly` unset → git can auto-invent identity | set it `true` |
| `user.name` | global `user.name` missing | set from existing identity (asks) |
| Missing `insteadOf` | a zone account lacks its canonical→alias rewrite | re-add the rewrite |

**Detects but reports only** (human judgment):

| Check | Problem |
|---|---|
| Host-vs-alias trap | the key is under an alias but remotes/usage hit the **real host**, which only matches `Host *` (with `IdentitiesOnly` and no `IdentityFile`) → `Permission denied` though the key exists (the exact bug in the guide). Suggests adding a real-host block or repointing remotes. |
| Secret in config | a global `insteadOf` (or any value) carries an embedded token/password → **flagged, never auto-edited**; advises rotating + removing. |
| Email divergence | two accounts in the same zone declare different emails. |
| Orphans | a marked block whose key file is gone; an `includeIf` whose `scope_dir` or identity file is missing. |
| Unmanaged block | a hand-written `Host` that overlaps a managed one (reported; never modified). |

```
$ gwt ssh doctor
→ Analyzing ~/.ssh/config and ~/.gitconfig
  ✗ perms     id_ed25519_dropi_gh           mode 0644           -> chmod 600
  ✗ identity  user.useConfigOnly            unset               -> set true
  ! trap      bitbucket.org                 remote uses real host, key only under alias 'dropi-bb'   review
  ! secret    url.insteadOf (bitbucket.org) embedded token      rotate & remove manually
2 fixable automatically · 2 require manual review.
Apply the 2 fixes? [y/N]
```

### 14.7 `gwt ssh remove <name> [--delete-key] [--keep-routing] [--dry-run]`

Removes the account safely.

- Removes the marked `Host <name>` block from `~/.ssh/config`.
- Removes the account's `insteadOf` rewrites from its zone identity file. If the zone becomes **empty**, removes the `includeIf` + identity file too (unless `--keep-routing`).
- **Keeps the key files** unless `--delete-key`. Never removes the key from the remote host (that is network; do it in the hosting UI).
- `--dry-run` shows the planned edits.

### 14.8 Cross-platform behavior (macOS · Linux · Windows)

The capability must work for developers on **macOS, Linux and Windows**. All OS-specific behavior is isolated in a thin platform layer; the rest of the logic (markers, parsing, idempotent edits, zones) is shared.

| Concern | macOS | Linux | Windows |
|---|---|---|---|
| Config paths | `~/.ssh/config`, `~/.gitconfig` | same | `%USERPROFILE%\.ssh\config`, `%USERPROFILE%\.gitconfig` |
| Key permissions | `chmod 600` enforced/checked | same | **N/A** — NTFS ACLs; perms checks marked N/A (as `ssh check` already does, §6.9) |
| Agent load | `ssh-add --apple-use-keychain` (persists in Keychain) | `ssh-add` (relies on a running `ssh-agent`; grove warns if `SSH_AUTH_SOCK` is unset) | `ssh-add` against the **OpenSSH Authentication Agent** service; grove warns if the service is not running/automatic |
| Keychain block line | adds `UseKeychain yes` to the `Host *` defaults | omitted (no such option) | omitted |
| `scope_dir` matching | `gitdir:` with POSIX path + trailing `/` | same | path normalized to forward slashes; grove writes `gitdir:` patterns git understands on Windows; trailing `/` enforced |
| Path handling | `pathlib`, never hand-built `/` | same | same — `pathlib` + explicit normalization for git's `gitdir:` |

Implementation notes:

- A `platform` module exposes `home_config_paths()`, `enforce_key_perms()`, `agent_add(key)`, `keychain_supported()`. The commands call these; they branch internally on `sys.platform`.
- Defaults in the `Host *` block are emitted conditionally: `AddKeysToAgent yes`, `IdentitiesOnly yes`, `ServerAliveInterval 60` everywhere; `UseKeychain yes` only on macOS.
- `doctor`'s permission check is **skipped (N/A)** on Windows, exactly like `ssh check`.
- Windows emergency note (consistent with §11): under Git Bash/WSL the POSIX path applies; native PowerShell uses the `%USERPROFILE%` paths. grove detects which environment it runs in.
- The **conformance suite** (§12) gains OS-tagged cases so Python/Go/Rust implementations stay in parity on all three platforms.

### 14.9 MCP exposure

Adds `grove_ssh_add`, `grove_ssh_accounts`, `grove_ssh_doctor`, `grove_ssh_remove` to the tool set (§13.2), same rules: typed inputs, structured output, confirmation by parameter. The canonical **enrichment** example: an agent calls `grove_ssh_add` and then uses its **GitHub/Bitbucket connector to upload the printed public key** — grove provisions locally, the agent does the network step. grove itself still never goes to the network.
