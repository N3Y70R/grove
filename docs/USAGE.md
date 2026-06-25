# Command reference — grove (`gwt`)

grove manages git worktrees with a consistent convention and structure. This document describes each command, its arguments, flags, and examples.

For installation, see [INSTALL.md](INSTALL.md). For the full design, see the specification.

---

## Model and structure

Each repo is set up with the **bare model**: a bare repository in `.bare/` and the worktrees as sibling folders. The bare's `HEAD` points to a parking branch (`worktree-config-root`) so it doesn't retain any real branch from the origin.

```
<repo>/
├── .bare/                     # bare repo + grove.toml (repo config)
├── production/                # special
├── temporary-unified-test/    # special
├── temp/                      # special: ephemeral / ticketless experiments
├── feature/  hotfix/  bugfix/ # types; tickets hang inside
│   └── PROJ-123-description/
└── release/
    └── v1.1.0/
```

The worktree folder path always matches the branch name.

---

## Global conventions

General form:

```
gwt <command> [arguments] [flags]
```

Except for `setup`, all commands must be run **inside a managed repo** (grove looks for `.bare/` upward from the current directory).

### Global flags

| Flag | Effect |
|---|---|
| `-h, --help` | Command help |
| `--version` | grove version |
| `-q, --quiet` | Warnings and errors only |
| `-v, --verbose` | Prints each git command executed, step by step |
| `--confirm-each` | Step-through: asks for confirmation before each git command (implies `-v`) |
| `--no-color` | Disables colors |
| `--json` | JSON output with status, reason, and result data (see below) |
| `-C <path>` | Runs as if the current directory were `<path>` |

### Exit codes

`0` success · `1` validation/convention error · `2` git error · `3` incorrect usage.

### JSON output (`--json`)

Since exit codes alone can be ambiguous, `--json` (global, for any command) emits a single object on stdout with the **status and the reason**, easy to parse in scripts/CI. In `--json` mode nothing else is printed and no interactive confirmations are requested.

Success:

```json
{
  "command": "create",
  "status": "ok",
  "exit_code": 0,
  "message": "Worktree created: .../feature/DROP-1-uno",
  "result": { "path": "...", "rel_path": "feature/DROP-1-uno", "branch": "feature/DROP-1-uno" },
  "log": ["slug: uno", "Validating: ...", "..."]
}
```

Error (the reason is in `message` and the type in `error_type`):

```json
{
  "command": "create",
  "status": "error",
  "exit_code": 1,
  "error_type": "ValidationError",
  "message": "Type 'chore' not allowed. Valid types: feature, hotfix, bugfix.",
  "log": []
}
```

The `result` field changes per command (`list` → array of worktrees; `doctor` → `{issues, auto_fixable, manual, applied}`; `remove` → `{removed: [...]}`; `ssh check` → `{hosts: [...]}`; etc.). Destructive operations that normally ask for confirmation (`sync`, `publish --regenerate`, `remove`) require `--yes`/`--force` in `--json` mode; if missing, they return an error explaining it instead of blocking.

---

## `gwt setup`

Initializes a new repo with the bare structure and writes its configuration.

```
gwt setup <url> [--name <dir>] [--into <path>] [--profile <name>]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<url>` | — (required) | Origin URL (any remote) |
| `--name <dir>` | name derived from the URL | Repo folder |
| `--into <path>` | current directory | Where to create the folder |
| `--profile <name>` | `default` | Policy profile to apply |
| `--ssh-alias <alias>` | autodetected | `~/.ssh/config` alias to use for the remote (`none` = URL as-is) |

What it does: clones the bare, configures the origin refspec, creates the parking branch, creates the base branch worktree (e.g. `production` or `main`) tracking the origin, and writes `.bare/grove.toml` with the profile's policy.

```
gwt setup git@github.com:acme/myrepo.git --profile personal
```

**SSH alias (canonical URL vs. local account).** The URL you copy from the remote is the canonical one (`git@github.com:org/repo.git`), without your local aliases. `setup` accepts it as-is. But if your `~/.ssh/config` has aliases whose `HostName` matches the URL's host (common when work and personal share `github.com`), grove detects it and:

- in **interactive** mode, asks which alias to use (or "as-is");
- with **`--ssh-alias <alias>`**, you choose it without a prompt (useful in scripts); `--ssh-alias none` forces the canonical URL;
- in **non-interactive mode without the flag**, it uses the URL as-is and warns.

If you choose an alias, grove rewrites the `origin` to that alias (`git@gh-work:org/repo.git`), so that every `fetch`/`push` uses the correct key. Verify with `gwt ssh check`.

```
gwt setup git@github.com:acme/backend.git --ssh-alias gh-work   # work account
gwt setup git@github.com:neytor/proyecto.git --ssh-alias gh-personal      # personal account
```

---

## `gwt create`

Creates worktrees. It has three subforms: ticket, release, and temp.

### Ticket

```
gwt create <TICKET-ID> <type> "<name>" [--base <branch>] [--print-path]
gwt create <type> "<name>"                              # when tickets = off
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<TICKET-ID>` | per policy | Ticket key (e.g. `PROJ-123`) |
| `<type>` | — | One of the repo's allowed types (`allowed_types`) |
| `"<name>"` | — | The name you choose; grove normalizes it to the slug format |
| `--base <branch>` | repo base branch | Branch to create from |
| `--print-path` | — | Prints only the created path (for `cd "$(...)"`) |
| `--dry-run` | — | Shows what it would do without executing |

The **name is provided by you**; grove only normalizes it (lowercase, hyphens, no accents) and validates it — it does not summarize it or derive it from any source.

`create` is only for **new** branches: it validates that the branch does not exist (neither locally nor in the origin) and that the folder is free; if something fails, it reports the reason. If the branch **already exists**, use `gwt track <branch>` (which derives the name from the existing branch). The new branch is not tracked to the base; the upstream is set on the first `git push -u`.

The ticket behavior depends on the repo's `tickets` policy:

- **`required`**: `gwt create PROJ-123 feature "fix login"` → `feature/PROJ-123-fix-login`
- **`off`**: `gwt create feature "fix login"` → `feature/fix-login`
- **`optional`**: accepts both; if the first argument is a ticket key, it uses it.

### Release

```
gwt create release <version> [--base <branch>]
```

- If `release/<version>` **already exists** in the origin → brings that version tracking `origin/release/<version>` (with upstream verification).
- If it **does not exist** → creates the new branch `release/<version>` from the release base (or `--base`).

```
gwt create release v1.2.0
```

### Temp

```
gwt create temp <name>
```

Creates an ephemeral worktree `temp/<name>` with a local branch of the same name. It is considered disposable: `doctor` may remove it during cleanup.

---

## `gwt track`

Brings in a branch that **already exists** (local or in the origin) and places it in the structure. **The name is derived from the branch** (you don't pass a slug). `track` *accommodates* what already exists, which is why it is more permissive than `create`.

```
gwt track <branch> [--as <type>/TICKET-XXXXX-slug]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<branch>` | — | Branch name (local or from the origin) |
| `--as <path>` | derived from the name | Explicit destination to relocate or force a type |

- If the branch is structurally valid (`<type>/TICKET-...`), grove infers the location by mirroring the name. It sets the upstream if the branch exists in the origin.
- **Permissive with the type:** if the type is not in `allowed_types` (e.g. `chore/PROJ-12345-...`), it brings it in anyway and **warns** (does not fail) — `allowed_types` only restricts `create`.
- If the branch is not parseable and you don't pass `--as`, it returns an error asking for the destination.

```
gwt track feature/PROJ-21114-refactor       # local or origin; name derived from the branch
gwt track chore/PROJ-12345-limpieza         # type not listed -> brought in with a warning
gwt track arreglo-rapido --as hotfix/PROJ-23300-fix-rapido
```

---

## `gwt list`

Lists the repo's worktrees.

```
gwt list [--type <type>] [--dirty] [--orphans] [--json]
```

| Flag | Description |
|---|---|
| `--type <type>` | Filters by type/kind (`feature`, `release`, `temp`, `special`, ...) |
| `--dirty` | Only worktrees with uncommitted changes |
| `--orphans` | Only orphaned records |
| `--json` | JSON output (for scripting) |

Columns: **folder · branch · ticket · git status** (ahead/behind, clean/dirty, upstream). In repos with `tickets = off` the ticket column is empty.

---

## `gwt doctor`

Detects —and optionally fixes— hygiene issues.

```
gwt doctor [--fix] [--dry-run] [--json]
```

| Flag | Behavior |
|---|---|
| (no flag) | Reports and, if there are automatic fixes, asks for confirmation |
| `--fix` | Applies the fixes without asking (for CI) |
| `--dry-run` | Reports only, does not modify |
| `--json` | Report in JSON |

**Fixes automatically:** orphans (prune), missing/incorrect upstream (set-upstream), release format with a hyphen (renames to `release/<v>`), flat folder whose branch is an allowed type (moves it to the convention).

**Reports only (does not touch):** type not in `allowed_types` (e.g. `chore/...` brought in with `track`) — warns that it does not conform to the configuration but does not move it; folder ticket ≠ branch ticket; nested worktrees. In `tickets = off` mode it does not report ticket mismatches.

---

## `gwt remove` (alias `gwt rm`)

Removes worktrees safely, individually or in bulk.

```
gwt remove <target> [--delete-branch] [--force] [--dry-run]
gwt remove --merged [--delete-branch] [--dry-run]
```

| Arg/Flag | Description |
|---|---|
| `<target>` | Ticket, branch, or worktree path (resolved; if ambiguous, lists candidates) |
| `--delete-branch` | Also deletes the local branch, only if it is merged to the base or pushed |
| `--force` | Removes even if there are uncommitted changes; deletes the branch even if not merged |
| `--merged` | Sweep: removes all ticket worktrees merged to the base |
| `--dry-run` | Shows what it would do without executing |

By default it removes the worktree and **keeps** the branch. The special ones (`production`, `temporary-unified-test`) are protected; a dirty worktree requires `--force`.

```
gwt remove DROP-123                      # by ticket; keeps the branch
gwt remove feature/DROP-123-fix          # by branch
gwt remove DROP-123 --delete-branch      # deletes branch if merged/pushed
gwt remove --merged --delete-branch      # cleans up everything already merged
gwt remove --merged --dry-run            # preview of the cleanup
```

---

## `gwt publish`

Brings ticket branches to the **shared integration branch** (to publish to a test environment). grove first locates that branch: existing worktree → origin → local branch; if it's not present it brings/creates it as described below.

```
gwt publish [<ticket|branch>...] [--into <branch>] [--regenerate] [--base <branch>] [--no-sync] [--yes] [--dry-run]
```

| Arg/Flag | Description |
|---|---|
| `[<ticket\|branch>...]` | Branches/tickets to publish (optional with `--regenerate`) |
| `--into <branch>` | Integration branch (default: config `integration_branch`) |
| `--regenerate` | Rebuild from the base (or **create** it from the base if it doesn't exist) |
| `--base <branch>` | Base for `--regenerate` (default: repo base branch) |
| `--no-sync` | Additive: do not sync the integration branch before merging |
| `--yes` | Do not ask for confirmation (force-push of `--regenerate` on an existing branch) |
| `--dry-run` | Shows what it would do without executing |

- **Additive (default):** syncs the integration branch → merges your branches → pushes. Requires the branch to already exist and **at least one target**; if it's missing, grove tells you to create it with `--regenerate --base`.
- **Regeneration (existing branch):** resets to the base → merges the branches in order → **force-pushes** (asks to confirm, unless `--yes`).
- **Regeneration (first time / branch missing):** **creates** the integration branch from `--base`, merges any targets and does a **normal push** (nothing to overwrite → no confirmation). Targets are optional, so you can seed an empty branch.

So `gwt publish --regenerate --base <branch>` is the single way to **create or rebuild** the integration branch. A merge conflict aborts the operation and leaves the worktree clean for you to resolve by hand.

```
gwt publish DROP-123                                  # additive: push your ticket to the shared env
gwt publish DROP-1 DROP-2 --regenerate                # rebuild the test branch with those two
gwt publish --regenerate --base production            # CREATE temporary-unified-test from production (empty)
gwt publish DROP-1 --regenerate --base production --into temporary-unified-test   # create from production + include DROP-1
gwt publish DROP-123 --into temporary-unified-test --dry-run
```

---

## `gwt sync`

Re-syncs a worktree with the origin (`fetch` + `reset --hard`). Useful for branches that are regenerated/force-pushed, like a shared test integration branch, where a normal `pull` diverges.

```
gwt sync [<target>] [--clean] [--yes] [--dry-run]
```

| Arg/Flag | Description |
|---|---|
| `<target>` | Ticket, branch, or path. By default, the worktree of the current directory |
| `--clean` | Also deletes untracked files (`git clean -fd`) |
| `--yes` | Does not ask for confirmation |
| `--dry-run` | Shows what it would do without executing |

**Destructive:** discards local unpushed commits and uncommitted changes. If it detects them, it warns and asks for confirmation (unless `--yes`).

```
gwt sync temporary-unified-test          # bring the regenerated version from the remote
gwt sync                                  # syncs the current worktree
gwt sync temporary-unified-test --clean --yes
```

---

## `gwt compare`

Shows the sync status (ahead/behind) between branches/worktrees. **Read-only.**

```
gwt compare [<a>] [<b>] [--vs <ref>] [--fetch]
```

| Arg/Flag | Description |
|---|---|
| `<a>` | Worktree/branch A (default: the current worktree) |
| `<b>` | Worktree/branch B (default: the upstream of A) |
| `--vs <ref>` | Compares **all** worktrees against `<ref>` (table) |
| `--fetch` | `git fetch` before comparing (the only network action) |

Each side is resolved as a worktree (ticket/branch/path) or as a git ref (`main`, `origin/main`, SHA). It reports `↑ahead ↓behind` and a status: in sync / ahead / behind / diverged.

```
gwt compare                       # current worktree vs its upstream
gwt compare PROJ-101 main         # your feature vs main
gwt compare --vs main --fetch     # all worktrees vs main (after fetch)
```

---

## `gwt patch`

Generates a patch of the worktree to share or back up **without pushing**.

```
gwt patch [<worktree>] [--base <ref>] [--format-patch] [--wip] [--output <path>] [--stdout]
```

| Arg/Flag | Description |
|---|---|
| `<worktree>` | Target worktree (default: the current one) |
| `--base <ref>` | Comparison base (default: repo base branch) |
| `--format-patch` | One `.patch` per commit (`git am`), in its own subfolder |
| `--wip` | Uncommitted changes (working tree vs HEAD) |
| `--output <path>` / `-o` | Explicit output path (file for diff, folder for format-patch) |
| `--stdout` | Prints the patch to stdout instead of writing a file |

By default it generates a **combined diff** (`git diff <base>...HEAD`, applicable with `git apply`) and saves it to `artifacts/patches/<branch>__<date>.diff`. The patches thus remain local artifacts (they are not versioned or pushed). If `artifacts_dir` is disabled, it falls back to the current directory.

```
gwt patch                              # patch of the current worktree vs its base
gwt patch PROJ-101 --format-patch      # one .patch per commit, ready for git am
gwt patch --wip --stdout               # my uncommitted changes, to stdout
```

---

## `gwt artifacts`

Prints (and creates if missing) the path of the repo's **local artifacts/documentation** folder.

```
gwt artifacts [<worktree>]
```

| Arg/Flag | Description |
|---|---|
| `<worktree>` | Optional: returns an `artifacts/<name>` subfolder (if it resolves to a worktree, uses its name; otherwise, a slug of the text) |

It is a **flat folder outside any worktree** (`artifacts/` by default, configurable with `artifacts_dir`): since it is not in any branch's tree, it is **never versioned or pushed** to the remote. It serves to store reports, notes, and skill outputs locally for reference. `setup` creates it during initialization.

```
cd "$(gwt artifacts)"             # enters the artifacts folder
gwt artifacts PROJ-101            # -> artifacts/feature-PROJ-101-.../  (worktree subfolder)
```

---

## `gwt config`

Shows or adjusts the repo configuration (`.bare/grove.toml`).

```
gwt config [show]                    # reports the configuration (with --json, in JSON)
gwt config set-ssh-alias <alias>     # sets the SSH alias and rewrites the origin
gwt config set-ssh-alias none        # returns to the canonical URL
```

- **`show`** (default): reports the repo, origin, and the effective policy. With the global `--json` flag, it delivers it as a parseable object (ideal for inspecting a repo from scripts).
- **`set-ssh-alias <alias>`**: saves `ssh_alias` in `grove.toml` and **rewrites the `origin`** to the alias (`git@github.com:...` → `git@gh-work:...`), so that `fetch`/`push` use the correct key. `none` resolves the alias's real host and returns the `origin` to its canonical form.

```
gwt config --json
gwt config set-ssh-alias gh-work
```

---

## `gwt ssh check`

Diagnoses the SSH configuration used to authenticate against git remotes. Useful when several accounts/remotes (work and personal) with different keys coexist. **Read-only**: it never modifies `~/.ssh/config`. It does not require being inside a managed repo.

```
gwt ssh check [<url-or-host>] [--all] [--live]
```

| Arg/Flag | Description |
|---|---|
| `<url-or-host>` | Git URL or host to diagnose. By default, the `origin` of the current repo |
| `--all` | Diagnoses all the `Host` entries declared in `~/.ssh/config` |
| `--live` | Runs `ssh -T` (with timeout) and reports the authentication result |

It reports, per host: the `HostName`, `User`, `IdentitiesOnly`, and the resolved `IdentityFile`(s) (via `ssh -G`), whether the key exists and has correct permissions (`600`; N/A on Windows), whether the `ssh-agent` is running and the identity is loaded, and —with `--live`— whether authentication works.

**Multiple accounts (work and personal):** the account is determined by the **host alias** you use in the `setup` URL (the alias stays in the `origin`, so `fetch`/`push` use the correct key with nothing more). If your work GitHub and your personal one share `github.com`, use different aliases in your `~/.ssh/config` (e.g. `Host gh-work` and `Host gh-personal`, each with its `IdentityFile`) and clone with them: `gwt setup git@gh-work:org/repo.git` vs `gwt setup git@gh-personal:your-username/repo.git`. `gwt ssh check` inside the repo confirms which key the `origin` will resolve.

**Users without `~/.ssh/config`:** the contextual diagnosis still works (`ssh -G` uses the default values); the report shows only the keys that exist and warns about the absent config, suggesting `--live`. In `--all` mode, if there is no config, grove gives an alternative overview: it lists the keys present in `~/.ssh`, the agent status, and diagnoses the known git hosts (`known_git_hosts` in config; by default `github.com`, `bitbucket.org`, `gitlab.com`).

```
gwt ssh check                              # the origin of the current repo
gwt ssh check git@github.com:acme/repo.git
gwt ssh check --all --live
```

---

## `gwt ssh add | accounts | doctor | remove`

Provision and maintain a multi-account SSH + git-identity setup at the **machine level** (your `~/.ssh/config` and `~/.gitconfig`). Unlike `ssh check` (read-only), these commands **write**. The guiding idea: the folder a repo lives in decides everything — which SSH key authenticates and which git identity signs commits — so you clone with the canonical URL and never type an alias. None of these require being inside a managed repo. grove edits only its own marker-delimited blocks (`# >>> grove:… >>>`) and backs files up before the first change; it never goes to the network (you upload the public key yourself).

### `gwt ssh add`

```
gwt ssh add <name> --host <host> [--email <e>] [--scope-dir <dir>]
            [--key <path>] [--no-identity] [--no-agent] [--no-passphrase]
            [--print-pubkey] [--dry-run]
```

| Arg/Flag | Default | Description |
|---|---|---|
| `<name>` | — | Account name = SSH `Host` alias (e.g. `dropi-gh`) |
| `--host <host>` | — | Real host (`github.com`, `bitbucket.org`, …) |
| `--email <e>` | — | git author email for this account's zone (required for identity routing) |
| `--scope-dir <dir>` | — | Folder that routes this account (defines/joins a zone). Omitting it implies `--no-identity` |
| `--key <path>` | `~/.ssh/id_ed25519_<name>` | Private key path |
| `--no-identity` | — | Configure SSH only; do not touch `~/.gitconfig` |
| `--no-agent` | — | Do not load the key into the agent |
| `--no-passphrase` | — | Generate the key without a passphrase (headless/CI; required with `--json`) |
| `--print-pubkey` | — | Print only the public key (for piping to an upload step) |
| `--dry-run` | — | Show the planned edits without writing |

It generates an ed25519 key, writes a marked `Host` block (with `IdentitiesOnly yes`), and — unless `--no-identity` — wires the **zone**: an `includeIf "gitdir:<scope-dir>"` in `~/.gitconfig` pointing to a grove-owned identity file (the zone's email + `insteadOf` rewriting `git@<host>:` → `git@<name>:`), and hardens the global config with `user.useConfigOnly = true`. Several accounts can share a zone (e.g. a GitHub and a Bitbucket account both under `~/dropi/`). Finally it loads the key into the agent (macOS Keychain when available) and prints the public key to upload.

```
gwt ssh add dropi-gh --host github.com --email victor.orobio@dropi.co --scope-dir ~/dropi
gwt ssh add personal-gh --host github.com --no-identity        # SSH only, no git routing
```

### `gwt ssh accounts`

```
gwt ssh accounts [--json]
```

Lists grove-managed accounts and zones (alias, host, key existence/agent state, zone folder + email, and routing coherence: `✓` ok, `!` partial, `—` none). Derived from the canonical files; there is no separate registry.

### `gwt ssh doctor`

```
gwt ssh doctor [--fix] [--dry-run] [--json]
```

Diagnoses and repairs the setup. **Auto-fixable** (with `--fix` or confirmation): open key permissions, a managed block missing `IdentitiesOnly yes`, a key not loaded in the agent, `user.useConfigOnly` unset, a missing `insteadOf` rewrite. **Report-only** (human judgment): the host-vs-alias trap (a real host with no dedicated block and no rewrite → would fail), an embedded secret/token in a `url.*` rewrite, orphans (missing key or zone), and an unset global `user.name`. Exit code is `1` while problems remain (CI gate), `0` when healthy.

### `gwt ssh remove`

```
gwt ssh remove <name> [--delete-key] [--keep-routing] [--dry-run]
```

Removes the account's `Host` block and its `insteadOf` rewrites from the zone; if the zone becomes empty, its `includeIf` and identity file are removed too (unless `--keep-routing`). Key files are kept unless `--delete-key`; the key is never removed from the remote host (do that in the hosting UI).

---

## Configuration and profiles

Each repo stores its policy in `.bare/grove.toml`, which `setup` writes from the profile. Precedence: internal defaults < global profile/config < repo config < environment variables < flags.

### Fields (`.bare/grove.toml`)

```toml
parking_branch    = "worktree-config-root"
default_base      = "production"
allowed_types     = ["feature", "hotfix", "bugfix"]
special_worktrees = ["production", "temporary-unified-test"]
temp_dir          = "temp"
artifacts_dir     = "artifacts"         # local artifacts folder ("" = disabled)
tickets           = "required"          # required | optional | off
ssh_alias         = "gh-work"          # ~/.ssh/config alias for the remote ("" = none)
ticket_prefixes   = ["DROP", "OPS"]     # accepted project keys
# ticket_pattern  = "DROP-\\d+"         # alternative: explicit regex (takes priority)
integration_branch = "temporary-unified-test"   # destination of `publish` ("" = none)
known_git_hosts   = ["github.com", "bitbucket.org", "gitlab.com"]  # fallback for `ssh check --all`

[release]
format       = "release/{version}"
default_base = "production"
```

### Built-in profiles

| Profile | base | types | tickets | integration |
|---|---|---|---|---|
| `default` | `main` | feature, fix, hotfix | `optional` | — |
| `personal` | `main` | feature, fix | `optional` | — |
| `gitflow` | `main` | feature, hotfix, bugfix, release | `required` | `develop` |

Custom profiles: define `[profiles.<name>]` in `~/.config/grove/config.toml` (it can override the built-in ones).

### `tickets` policy

- **`required`**: requires a ticket key in `create`.
- **`optional`**: accepts a key or just a description (it detects it).
- **`off`**: names only by description; disables the ticket invariant and the `doctor` check.

### Ticket pattern (`ticket_pattern`)

> grove **never queries** Jira, Linear, GitHub Issues, or any platform: the ticket key and the description are provided by whoever invokes the command. The pattern only defines how to *recognize* the key within the name; all the information arrives by parameter (see "Design principles" in the spec).

Defines **what string counts as a ticket key** within folder and branch names. From it, grove extracts and uses that identifier in:

- **`create`**: validates the key and builds the name (`feature/DROP-101-...`). In `optional` mode, it is what allows it to **detect** whether the first argument is a ticket or a description.
- **`track`**: parses the key from the origin branch name to classify and place it.
- **`list`**: the TICKET column is obtained by applying the pattern to the worktree name.
- **`doctor`**: detects the "folder ticket ≠ branch ticket" case.
- **`remove` / `publish`**: when you resolve a target by ticket (`gwt remove DROP-101`), it looks for the worktree whose name contains that key.

**Generic default:** `[A-Z][A-Z0-9]+-\d+`, which recognizes any Jira-style key (`DROP-123`, `PROJ-45`, `ABC-9`). It works without configuring anything.

**Why restrict it** to your project (e.g. `DROP-\d+`):

- Avoid **false positives**: so that a branch like `feature/API-2-experimento` is not confused with a ticket.
- Enforce **consistency** in `required` mode: so that only keys from your real project are accepted.

**How to set it** (from highest to lowest priority):

1. Environment variable `GROVE_TICKET_PREFIX` — one or more keys separated by comma/space: `GROVE_TICKET_PREFIX="DROP OPS"`.
2. `ticket_pattern` in `grove.toml` — explicit regex for advanced cases: `ticket_pattern = "DROP-\\d+"`.
3. `ticket_prefixes` in `grove.toml` — the recommended form: a list of keys, e.g. `ticket_prefixes = ["DROP", "OPS"]`. grove converts it into the pattern `(?:DROP|OPS)-\d+`.

If you don't define any, the generic pattern that accepts any Jira-style key is used. For **multiple project keys** in the same repo, use `ticket_prefixes` (or the generic one, which already covers them all).

> In repos with `tickets = off` the pattern is **not used**: worktrees are named only by description. It only comes into play in `required` or `optional` mode.

---

## Verbose and step-through

With `-v` grove prints each real git command before executing it (useful for auditing or learning). `--confirm-each` additionally asks for confirmation before each one; reserved for delicate operations.

```
gwt setup git@github.com:acme/myrepo.git -v
```
