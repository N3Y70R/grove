---
name: grove
description: Work in git repos managed by grove (the `gwt` command and the grove_* MCP tools), where each branch lives in its own worktree folder next to a `.bare/` repository. Use to start or resume work on a ticket (e.g. PROJ-123), bring remote changes safely, clean up merged worktrees, adopt an existing clone, or diagnose repo hygiene (git locks, missing identity). Triggers on gwt, grove, worktrees, `.bare/`, "start working on ticket X", "update from origin", and in Spanish "arranca / empecemos el TICKET-123", "trae lo de origin", "limpia los worktrees".
license: GPL-3.0-or-later
compatibility: Requires grove (pipx install "grove-wt[mcp]") and git. Optional relative worktree paths need git >= 2.48.
metadata:
  author: N3Y70R
  grove-version: "0.13.0"
---

# grove

A grove repo is a folder with the git repository in `.bare/` and **one folder
per branch**: `main/` (the base), `feature/PROJ-1-login/`, `temp/spike/`…
The folder path is the branch name. Work happens inside those folders; never
`git checkout` another branch inside a worktree.

Drive it with the grove MCP tools when they are available (always pass
`cwd` = the repo folder, the one containing `.bare/`), otherwise with `gwt`.
Every MCP tool's description ends with its `CLI:` equivalent.

**Know the repo only by name?** `grove_repos` (`gwt repos`) lists the managed
repos under the user's identity zones or the folders you pass. If it finds
nothing, ask the user for the absolute path — never guess one.

## Pick the operation

| The user wants to… | MCP tool | CLI |
|---|---|---|
| start / resume work on a ticket | `grove_start(type, name, ticket, base?)` | `gwt start PROJ-1 feature "login"` |
| find a repo's path | `grove_repos(paths?)` | `gwt repos [PATH …]` |
| see the worktrees and their state | `grove_list` | `gwt list` |
| how far is a worktree from `main` (or any branch) | `grove_compare(vs="main")` | `gwt compare --vs main` |
| bring what's new on origin (safe) | `grove_fetch` | `gwt fetch` |
| bring an existing branch into a folder | `grove_track(branch)` | `gwt track <branch>` |
| remove finished work | `grove_remove(merged=true, dry_run=true)` first | `gwt remove --merged --dry-run` |
| fix hygiene problems | `grove_doctor`, then `fix=true` | `gwt doctor --fix` |
| manage an existing normal clone | `grove_convert(path, dry_run=true)` first | `gwt convert <path>` (alias `adopt`) |
| clone a new repo | `grove_setup(url, profile?)` | `gwt setup <url>` |

Default to **`grove_start`** for anything like "work on / start / continue
ticket X": it fetches, then returns the existing worktree, brings the branch if
someone already pushed it, or creates it from the fresh `origin/<base>`. Use
`grove_create` only when the user explicitly wants a *new* worktree.

Its `mode` tells you what happened: `existing` — the worktree was already
there (continue in it; check `dirty`); `resumed` — the branch existed and was
brought into a new folder, possibly **with commits pushed by someone else**
(read `git log` before building on it); `created` — a new branch from the
freshly fetched `origin/<base>`.

## Everyday flow

- [ ] `grove_start` → note `path`, `mode` and `next_steps`
- [ ] work and commit inside `path`
- [ ] first push: `git push -u origin <branch>` (from `next_steps`)
- [ ] on a ticket that lasts days, stay current (see below)
- [ ] after the merge: `grove_remove(merged=true, dry_run=true)`, review, then
      `grove_remove(merged=true, delete_branch=true, confirm=true)`

### When origin moved while you worked

1. `grove_fetch` — only moves `origin/*`; each row's `status` is measured
   against its `compared_to` (the upstream, or the base before the first push).
2. `behind` → `git merge --ff-only` inside the worktree.
3. `diverged` on your branch → someone else pushed too: `git pull --rebase`
   (or merge). `--ff-only` refuses a diverged branch; that is expected.
4. The **base** moved (`grove_compare(vs="<base>")` shows how far) →
   `git rebase origin/<base>` for a branch only you use, or
   `git merge origin/<base>` when it is shared or already in review. After a
   rebase, push with `git push --force-with-lease`.
5. Never answer `diverged` with `grove_reset`: it throws your commits away.

## Gotchas

- **`grove_reset` / `gwt reset` DISCARDS local commits and changes** (reset
  --hard to origin). `grove_sync` / `gwt sync` is its deprecated alias. To
  *bring* remote changes use `grove_fetch`, then `git merge --ff-only` inside
  the worktree. Reset only branches that get force-pushed, and only when asked.
- **Only touch the repos the user asked about.** Several grove repos may sit
  side by side (work and personal); never run fixes, migrations or config
  changes on one the user didn't name.
- Destructive tools need `confirm=true`; `grove_remove` accepts `dry_run=true`
  without confirm — **preview before sweeping**. "Merged" includes brand-new
  branches with no commits of their own.
- The base worktree and special worktrees are protected from `remove`.
- **"Another git process seems to be running"** after a crash or a sandboxed
  environment that can't delete files: `grove_doctor` reports the lock; once it
  is stale (≥60 s, no git running; or ≥10 min) `fix=true` removes it. Never
  delete `.lock` files by hand while git may be running.
- **Seen from another mount (container, VM)**, a worktree's `.git` holds an
  absolute path of the other machine. Use each row's `gitdir` from
  `grove_list`: `GIT_DIR=<repo>/<gitdir> GIT_WORK_TREE=<repo>/<rel_path> git …`.
  Do not run `git worktree prune` from there.
- **`relative_worktrees = true` makes git < 2.48 refuse the whole repo.** Only
  enable it if every git touching the repo is new enough.
- **Check the versions match:** if `grove_config().version` differs from this
  file's `metadata.grove-version`, either the MCP server is stale (restart the
  MCP client after upgrading grove; new tools may need a tool-list refresh) or
  this skill is: `grove_doctor` reports `skill-outdated` and `fix=true`
  refreshes an untouched copy. Don't trust tool names here until they match.
- Create and remove worktrees **only through grove** — never
  `git worktree add` / `git worktree remove` by hand: the folder would miss the
  naming convention, the upstream rules and `doctor`'s checks.
- Git config set from any worktree is **shared**: it lands in `.bare/config`
  and applies to every worktree, present and future (hooks path, identity,
  signing). Set it once; don't repeat it per worktree.
- The command is **`gwt`** (also installed as `grove`); the PyPI package is
  `grove-wt`.
- grove never queries Jira/GitHub issues: ticket keys and names come from the
  user.

## When something goes wrong

Read [references/troubleshooting.md](references/troubleshooting.md) when a
grove command fails, a push is rejected, `grove_doctor` reports something you don't recognize, git
refuses to open the repo, or an upgrade doesn't show up.

Read [references/configuration.md](references/configuration.md) when the user
wants to change the base branch, ticket rules, profiles or relative worktree
paths.
