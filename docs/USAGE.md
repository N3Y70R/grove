# Command reference — grove (`gwt`)

grove manages git worktrees with a consistent convention and structure. This document describes each command, its arguments, flags, and examples.

For installation, see [INSTALL.md](INSTALL.md). For the full design, see the specification.

---

## Model and structure

Each repo is set up with the **bare model**: a bare repository in `.bare/` and the worktrees as sibling folders. The bare's `HEAD` points at the base branch; no internal branch is created. (Repos made before 0.10.0 have a `worktree-config-root` branch: `gwt doctor --fix` removes it.)

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

The `result` field changes per command (`list` → array of worktrees; `doctor` → `{issues, auto_fixable, manual, applied}`; `remove` → `{removed: [...]}`; `ssh check` → `{hosts: [...]}`; etc.). Destructive operations that normally ask for confirmation (`reset`, `publish --regenerate`, `remove`) require `--yes`/`--force` in `--json` mode; if missing, they return an error explaining it instead of blocking.

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

What it does: clones the bare, configures the origin refspec, points the bare `HEAD` at the base, creates the base branch worktree (e.g. `production` or `main`) tracking the origin, and writes `.bare/grove.toml` with the profile's policy.

**Already have the repo cloned?** Don't re-clone: use [`gwt convert`](#gwt-convert) (alias `gwt adopt`). If `setup`'s destination is already a git clone, it stops and suggests exactly that command.

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

(Use `--no-git-pointer` to skip writing the root `.git` pointer.)

**If setup fails partway**, grove removes the half-created folder so your next try starts clean (no leftover `.bare/` blocking the retry). Add `--keep-on-error` if you'd rather keep the partial folder to inspect what went wrong.

---

## `gwt convert`

Converts (adopts) an **existing normal clone** into the grove model, without re-cloning. Alias: **`gwt adopt`**.

```
gwt convert [path] [--into <dir>] [--profile <name>] [--branches current|current+base|all]
                   [--no-fetch] [--force] [--no-git-pointer] [--keep-on-error] [--dry-run]
```

| Arg/Flag | Description |
|---|---|
| `[path]` | The existing clone (default: current directory) |
| `--into <dir>` | Build a new grove repo there; leave the source clone untouched |
| `--profile <name>` | Policy profile to apply and record in `.bare/grove.toml` (default: `default`) |
| `--branches` | Worktrees to materialize (default: `current+base`) |
| `--no-fetch` | Don't contact origin (offline) |
| `--force` | Proceed even if submodules or Git LFS are detected (blocked by default) |
| `--no-git-pointer` | Don't write the root `.git` pointer |
| `--keep-on-error` | On failure, keep partial output (default: clean it up) |
| `--dry-run` | Print the plan without changing anything |

- **In-place (default):** reuses `.git` (→ `.bare/`), **auto-stashes and restores** your uncommitted work in the current worktree, and **preserves ignored files** (moved into the current worktree — also those nested inside tracked folders, like `python/.venv`). If an ignored file already exists in the worktree with other content, it is **kept at the root and reported**, never overwritten. Keeps all local branches/stashes/config.
- **Config:** writes `.bare/grove.toml` with the chosen profile and the detected base, like `setup`.
- **`--into`:** safest; the source is left intact (your WIP stays there).
- **Cleanup on failure:** with `--into`, a failed conversion removes the new folder (the source is never touched) so retries are clean. In-place never auto-deletes (it could discard files already moved into a worktree): it restores the auto-stash if it fails before any change, otherwise it stops and reports for manual inspection. `--keep-on-error` preserves partial `--into` output.

```
gwt convert                                   # convert the repo in the current folder
gwt convert ~/dropi/api-backend --branches all
gwt convert ~/dropi/api-backend --into ~/dropi/api-backend-grove   # keep the original
gwt convert --dry-run                         # preview only
gwt convert --profile personal                # personal repo: record the personal profile
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

`create` is only for **new** branches: it validates that the branch does not exist (neither locally nor in the origin) and that the folder is free; if something fails, it reports the reason. If the **base** doesn't exist, it names the existing candidates and the fix (`--base <candidate>`, or `gwt config set default_base <candidate>` when your `grove.toml` points at a base the repo doesn't have). If the branch **already exists**, use `gwt track <branch>` (which derives the name from the existing branch). The new branch is not tracked to the base; the upstream is set on the first `git push -u`.

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

## `gwt start`

**Start or resume work on a ticket in one command.** Idempotent: you can run it every time you sit down to work on a ticket.

```
gwt start <TICKET-ID> <type> "<name>" [--base <branch>] [--no-fetch] [--print-path]
gwt start <type> "<name>"            # repos with optional/off tickets
```

What it does, in order:

1. `git fetch origin` (skip with `--no-fetch`), so the base is current;
2. if the ticket already has a worktree → returns it (**existing**);
3. if a branch for the ticket exists, locally or on origin, without a worktree → brings it like `gwt track` (**resumed**);
4. otherwise → creates the worktree from **`origin/<base>`** (the base you just fetched; the local base if it isn't on origin) (**created**). The new branch doesn't track the base; `git push -u` sets its upstream.

```
✓ Created: feature/PROJ-101-login (from origin/main)
  cd /Users/me/code/app/feature/PROJ-101-login
  git push -u origin feature/PROJ-101-login   # first push creates the branch on origin
```

If the ticket matches several worktrees or branches, it stops and lists them. `cd "$(gwt start PROJ-101 feature login --print-path)"` jumps straight in. With `--json`: `{mode, path, rel_path, branch, base, ticket, upstream, gitdir, next_steps}`.

**`start` or `create`?** `create` only makes new worktrees, from the base as it is locally, and fails if the branch exists. `start` is the everyday command: it fetches, reuses, resumes or creates.

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
| `--type <type>` | Filters by type/kind (`feature`, `release`, `temp`, `special`, `base`, ...) |
| `--dirty` | Only worktrees with uncommitted changes |
| `--orphans` | Only orphaned records |
| `--json` | JSON output (for scripting) |

Columns: **folder · branch · ticket · git status** (ahead/behind, clean/dirty, upstream, and `merged` when the branch has no commits outside the base). A branch with no upstream yet is measured against the base: `↑3 ↓0 vs main (no upstream)`. In repos with `tickets = off` the ticket column is empty.

`--json` rows also include **`compared_to`** (the upstream, or the base when there is no upstream), **`merged`** (see `remove --merged`) and **`gitdir`**, the worktree's internal directory relative to the repo root (e.g. `.bare/worktrees/PROJ-1-login`; git names it after the last path component). Useful when the repo is mounted at another path (container, VM): `GIT_DIR=<repo>/<gitdir> GIT_WORK_TREE=<repo>/<rel_path> git status`.

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

**Fixes automatically:** orphans (prune), missing/incorrect upstream (set-upstream), release format with a hyphen (renames to `release/<v>`), flat folder whose branch is an allowed type (moves it to the convention), missing root `.git` pointer, worktree paths that don't match `relative_worktrees`, a bare `HEAD` not pointing at the base and the legacy `worktree-config-root` branch (pre-0.10.0 repos; deleted only if it has no commits of its own), **orphaned git locks / leftover temp objects** in `.bare` (e.g. a `HEAD.lock` that makes git say *"Another git process seems to be running"*), and an **installed Agent Skill written for another grove version** (`skill-outdated`, in `~/.agents/skills` or `~/.claude/skills`) when the copy was not edited — it is reinstalled. A lock counts as orphaned when it is ≥60 s old and no git process is running on this machine, or ≥10 min old regardless.

**Reports only (does not touch):** type not in `allowed_types` (e.g. `chore/...` brought in with `track`) — warns that it does not conform to the configuration but does not move it; folder ticket ≠ branch ticket; nested worktrees; **recent locks** (maybe in use); worktrees with **no git author identity** (a commit would fail with *"Author identity unknown"*); an outdated Agent Skill that was **edited** (or installed by 0.12.0, which wrote no install manifest) — review it, then `gwt skill install --force` — and an outdated **project** copy (`<worktree>/.agents/skills/grove`, which is committed); and a user-level copy **edited since install** (`skill-edited`: upgrades won't refresh it). The report ends with the Agent Skill copies it checked (`skills` in `--json`: path, scope, version, `outdated`, `edited`). In `tickets = off` mode it does not report ticket mismatches.

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

By default it removes the worktree and **keeps** the branch. The base worktree and the special ones (`production`, `temporary-unified-test`) are protected; a dirty worktree requires `--force`. Parent folders left empty (e.g. `feature/`) are removed.

"Merged" = the branch has no commits outside the base (a brand-new branch with no commits also counts). Check it first with `gwt list` (the status shows `merged`) or `gwt remove --merged --dry-run`.

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

## `gwt reset` (formerly `gwt sync`)

**Discards local work:** resets a worktree to its origin branch (`fetch` + `reset --hard`). Useful for branches that are regenerated/force-pushed, like a shared test integration branch, where a normal `pull` diverges.

> Renamed in 0.7.0: `sync` sounded like "update from the remote". `gwt sync` still works but warns. To **only bring** remote changes without touching anything, use `gwt fetch`.

```
gwt reset [<target>] [--clean] [--yes] [--dry-run]
```

| Arg/Flag | Description |
|---|---|
| `<target>` | Ticket, branch, or path. By default, the worktree of the current directory |
| `--clean` | Also deletes untracked files (`git clean -fd`) |
| `--yes` | Does not ask for confirmation |
| `--dry-run` | Shows what it would do without executing |

**Destructive:** discards local unpushed commits and uncommitted changes. If it detects them, it warns and asks for confirmation (unless `--yes`).

```
gwt reset temporary-unified-test         # take the regenerated version from the remote
gwt reset                                 # resets the current worktree
gwt reset temporary-unified-test --clean --yes
```

---

## `gwt fetch`

Brings what's new on origin and shows where each worktree stands. **Safe:** it only updates the `origin/*` refs and never modifies a worktree (compare with `gwt reset`, which discards local work).

```
gwt fetch [--prune]
```

| Flag | Description |
|---|---|
| `--prune` | Also drop `origin/*` refs of branches deleted on the remote |

```
✓ Fetched from origin (worktrees untouched)
  WORKTREE                STATUS
  feature/PROJ-101-login  ↑2 ↓0 vs main  ahead
  main                    ↑0 ↓3 vs origin/main  behind
To bring a worktree up to date: cd <worktree> && git merge --ff-only (or git pull). grove never changes your worktrees on fetch.
```

A branch with no upstream is measured against the base (see `list`). With `--json`: `{prune, worktrees: [{worktree, branch, compared_to, ahead, behind, status, dirty}]}`.

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
gwt config set <key> <value>         # set a key in grove.toml
gwt config unset <key>               # remove a key (revert to the profile default)
gwt config edit                      # open grove.toml in $EDITOR
gwt config set-ssh-alias <alias>     # sets the SSH alias and rewrites the origin
gwt config set-ssh-alias none        # returns to the canonical URL
```

- **`show`** (default): reports the repo, origin, and the effective policy. With the global `--json` flag, it delivers it as a parseable object (ideal for inspecting a repo from scripts).
- **`set <key> <value>`**: writes one key into `grove.toml`. Settable keys: `default_base`, `tickets` (`off`/`optional`/`required`), `allowed_types`, `special_worktrees`, `temp_dir`, `artifacts_dir`, `integration_branch`, `ssh_alias`, `ticket_prefixes`, `ticket_pattern`, `known_git_hosts`. List keys take a comma-separated value (`feature,hotfix,release`); `ticket_prefixes` and `ticket_pattern` are mutually exclusive (setting one clears the other).
- **`unset <key>`**: removes the key so the value falls back to the active profile/default.
- **`edit`**: opens `grove.toml` in `$EDITOR` (or `$VISUAL`, else `vi`) for free-form edits.
- **`set-ssh-alias <alias>`**: saves `ssh_alias` in `grove.toml` and **rewrites the `origin`** to the alias (`git@github.com:...` → `git@gh-work:...`), so that `fetch`/`push` use the correct key. `none` resolves the alias's real host and returns the `origin` to its canonical form.

```
gwt config --json
gwt config set default_base production
gwt config set allowed_types feature,hotfix,release
gwt config unset ssh_alias
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

## `gwt ssh aliases`

Shows the **repo↔alias map**: the `~/.ssh/config` aliases whose resolved `HostName` matches a repo's origin host (or a host/URL you pass). Answers "which alias should this repo use?" — the friction point when several accounts share a host like `github.com`. **Read-only.**

```
gwt ssh aliases [<url-or-host>]
```

By default it uses the current repo's `origin`. If the origin already points at an alias (e.g. `git@gh-work:…`), grove resolves the real host first, lists every alias for it, and marks the one currently applied. With no repo, pass a URL or host. List the candidates, then pin one with `gwt config set-ssh-alias <alias>`.

```
gwt ssh aliases                            # aliases for the current repo's host
gwt ssh aliases git@github.com:acme/repo.git
gwt ssh aliases github.com --json
```

---

## `gwt skill install`

Installs grove's **Agent Skill** ([agentskills.io](https://agentskills.io)): instructions that teach an AI agent how to work with grove — `start` for tickets, `fetch` vs `reset`, previewing removals, `doctor` for locks — and the gotchas learned in real use. The skill ships inside grove, so the installed copy matches your grove version.

```
gwt skill install                  # ~/.agents/skills/grove  (cross-client convention)
gwt skill install --claude         # ~/.claude/skills/grove
gwt skill install --project        # <current worktree>/.agents/skills/grove
gwt skill install --path DIR       # DIR/grove
gwt skill install --force          # overwrite a copy that differs (edited or another version)
gwt skill install --dry-run        # show what would be installed
```

Idempotent: if the installed copy is identical it reports `unchanged`; if it is an untouched copy from an older grove it is refreshed (`updated`); if it was edited — or has no install manifest, like copies installed by 0.12.0 — it refuses unless `--force` (saying which grove version the copy is for), so your edits are never lost silently. `--dry-run` never fails: for such a copy it reports `edited` (or `unverified`, no manifest) and the files that differ. So after upgrading grove, `gwt skill install` (and `--claude`) is enough. Each install writes `.grove-install.json` next to the skill (grove version + a hash per file), which lets `gwt doctor` tell an untouched outdated copy — refreshed with `--fix` — from an edited one. Re-run it after upgrading grove. MCP: `grove_skill_install`. The source is [`skills/grove/`](../skills/grove/SKILL.md) in the repo.

---

## `gwt repos`

Lists the grove-managed repos (folders with `.bare/`) on this machine — handy when you, or an agent, know a repo by name but need its path.

```
gwt repos                     # under your identity zones (`gwt ssh add`) + repos_roots
gwt repos ~/code ~/work       # under these folders
gwt repos --depth 4 --json
```

grove keeps no registry of repos: it searches the given folders (default: the zone directories of `~/.gitconfig`'s `includeIf gitdir:` blocks, plus the folders listed in `repos_roots`), up to `--depth` levels (default 3), skipping hidden folders and never descending into a repo it found. Each row shows the path, the base (`default_base` from `.bare/grove.toml`, else the bare `HEAD`), the effective profile (`default` when `grove.toml` names none) and `origin` as git uses it (`git remote get-url`, with any `insteadOf` rewrite applied — the same value `gwt config` shows). Read-only. MCP: `grove_repos`.

Repos that live outside any identity zone — for example personal repos reached through an SSH alias, with no `gwt ssh add --scope-dir` — are found by listing their parent folders once in `~/.config/grove/config.toml`:

```toml
repos_roots = ["~/neytor/workspace", "~/code"]
```

`~` is expanded; missing folders are skipped. Explicit `PATH` arguments replace the defaults for that call.

---

## `gwt skill status`

State of the installed Agent Skill copies (`~/.agents/skills/grove`, `~/.claude/skills/grove`) against the grove you are running: version, `outdated`, `edited` (from the install manifest; `no manifest` for copies installed by 0.12.0). **Needs no repo**, so you can check right after installing grove. Ends with what to do next, if anything. MCP: `grove_skill_status`. (`gwt doctor` reports the same, plus project copies, inside a repo.)

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

## Recipes

Short answers to the questions that come up most. Each links to the full reference above.

### Start working on a ticket (the everyday command)

`gwt start PROJ-101 feature "login"`: it fetches, then reuses the ticket's worktree, brings its branch if a teammate already pushed it, or creates it from the fresh `origin/<base>`. Add `--base <branch>` to start from something else. See [`gwt start`](#gwt-start).

### Create a worktree from any base

The **`--base <branch>`** option works for every kind of worktree (MCP: `base`):

```
gwt create PROJ-101 feature "login" --base release/v2.3    # ticket
gwt create release v2.4.0 --base production                # release
gwt create temp spike-cache --base develop                 # temp
gwt create PROJ-102 bugfix "fix" --base origin/hotfix-x    # a branch that only exists on origin
```

Without `--base` it uses the repo's `default_base` (`gwt config` shows it; change it with `gwt config set default_base <branch>`). If the base doesn't exist, grove names the branches that do and the fix.

### Start using grove on a repo you already cloned

Don't re-clone: `gwt convert ~/code/api` (alias `gwt adopt`). Preview with `--dry-run`; choose the policy with `--profile`. See [`gwt convert`](#gwt-convert).

### Bring what's new on the remote — without losing anything

`gwt fetch` fetches from origin and shows every worktree's ahead/behind against its upstream. It never touches your worktrees; to bring one up to date, `cd` into it and `git merge --ff-only` (or `git pull`). To see everything against one branch instead: `gwt compare --vs main --fetch`.

`gwt reset <worktree>` is different: it **discards** local commits and changes to match origin. Use it only for branches that get force-pushed (e.g. an integration branch).

### Clean up merged work safely

```
gwt list                       # the status shows "merged" per worktree
gwt remove --merged --dry-run  # what would be removed
gwt remove --merged --delete-branch
```

"Merged" = no commits outside the base, which includes a brand-new branch with no commits yet.

### Git complains about a lock ("Another git process seems to be running")

`gwt doctor`, then `gwt doctor --fix` once the lock is stale (≥60 s with no git running, or ≥10 min).

---

## Configuration and profiles

Each repo stores its policy in `.bare/grove.toml`, which `setup`/`convert` write from the profile (a full snapshot, plus `profile = "<name>"`).

**How the effective policy is built** on every command, from lowest to highest priority:

1. grove's internal defaults;
2. the repo's **profile** (the `profile` key in `grove.toml`; repos created before 0.8.2 use `default`);
3. the keys in `.bare/grove.toml`;
4. environment variables (`GROVE_TICKET_PREFIX`, ticket keys only);
5. command flags (e.g. `--base`).

A profile is a **template**: editing it later does **not** change repos that already exist (their keys are written in `grove.toml`). Only a key you remove with `gwt config unset` falls back to the repo's profile.

### Editing the configuration

| I want to… | Do this |
|---|---|
| Change one value in **this repo** | `gwt config set default_base production` |
| Go back to the profile's value | `gwt config unset default_base` |
| Edit this repo's config freely | `gwt config edit` (opens `.bare/grove.toml`) |
| See the effective values | `gwt config` (or `gwt config --json`) |
| Reuse a policy across **many repos** | define a profile in `~/.config/grove/config.toml` and use `setup --profile <name>` / `convert --profile <name>` |

A **work-style profile** (base `production`, required tickets with your project keys, a shared integration branch) looks like this in `~/.config/grove/config.toml`:

```toml
[profiles.work]
default_base       = "production"
allowed_types      = ["feature", "hotfix", "bugfix"]
special_worktrees  = ["production", "temporary-unified-test"]
tickets            = "required"
ticket_prefixes    = ["PROJ"]
integration_branch = "temporary-unified-test"

[profiles.work.release]
default_base = "production"
```

```
gwt setup git@github.com:acme/api.git --profile work     # new clone
gwt convert ~/code/api --profile work                     # clone you already have
```

A profile with the name of a built-in one (`default`, `personal`, `gitflow`) overrides it.

### Fields (`.bare/grove.toml`)

```toml
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
relative_worktrees = false              # opt-in relative worktree paths (git >= 2.48), see below

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

### Relative worktree paths (`relative_worktrees`, opt-in)

By default git writes **absolute** paths in each worktree's `.git` file, so if the repo is seen from another path (a container, a VM, another machine's mount), git doesn't work inside the worktrees there. With git **≥ 2.48** grove can make them **relative**:

```
gwt config set relative_worktrees true    # converts the existing worktrees now
gwt config set relative_worktrees false   # converts them back
```

When enabled, grove sets `worktree.useRelativePaths` in the bare, so every later `git worktree add/move/repair` (grove's or yours) is relative too. A profile can include `relative_worktrees = true`; `setup`/`convert` then apply it.

**Why it's off by default:** it is not backward compatible. git marks the repo with `extensions.relativeWorktrees`, and **older git (< 2.48) and libgit2-based tools (< 1.9.4, e.g. TortoiseGit) refuse to open the repository**. Enable it only if every git that touches the repo is new enough. Turning it off converts the worktrees back and removes the mark. With an old git, grove refuses to enable it and says why; `gwt doctor` reports and fixes a repo whose paths don't match the setting.

Without this option, `gwt list --json` still gives each worktree's `gitdir`, enough to use `GIT_DIR`/`GIT_WORK_TREE` from another mount.

### `tickets` policy

- **`required`**: requires a ticket key in `create`.
- **`optional`**: accepts a key or just a description (it detects it).
- **`off`**: names only by description; disables the ticket invariant and the `doctor` check, and nothing is read as a ticket — a branch like `feature/abc-12-login` shows no ticket in `list` or `start`.

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

If you don't define any, the generic pattern that accepts any Jira-style key is used. **Recommendation:** set `ticket_prefixes` whenever the repo uses tickets. With the generic pattern and `tickets = "optional"`, any `word-number` in a name (`api-2`, `python-0`) can be read as a ticket; version numbers are excluded since 0.6.1, but other words are not. For **multiple project keys** in the same repo, use `ticket_prefixes` (or the generic one, which already covers them all).

> In repos with `tickets = off` the pattern is **not used**: worktrees are named only by description. It only comes into play in `required` or `optional` mode.

---

## Verbose and step-through

With `-v` grove prints each real git command before executing it (useful for auditing or learning). `--confirm-each` additionally asks for confirmation before each one; reserved for delicate operations.

```
gwt setup git@github.com:acme/myrepo.git -v
```
