---
name: grove
description: Work in git repos managed by grove (the `gwt` command and the grove_* MCP tools), where each branch lives in its own worktree folder next to a `.bare/` repository. Use to start or resume work on a ticket (e.g. PROJ-123), bring remote changes safely, clean up merged worktrees, adopt an existing clone, or diagnose repo hygiene (git locks, missing identity). Triggers on gwt, grove, worktrees, `.bare/`, "start working on ticket X", "update from origin".
license: GPL-3.0-or-later
compatibility: Requires grove (pipx install "grove-wt[mcp]") and git. Optional relative worktree paths need git >= 2.48.
metadata:
  author: N3Y70R
  grove-version: "0.12.0"
---

# grove

A grove repo is a folder with the git repository in `.bare/` and **one folder
per branch**: `main/` (the base), `feature/PROJ-1-login/`, `temp/spike/`…
The folder path is the branch name. Work happens inside those folders; never
`git checkout` another branch inside a worktree.

Drive it with the grove MCP tools when they are available (always pass
`cwd` = the repo folder, the one containing `.bare/`), otherwise with `gwt`.
Every MCP tool's description ends with its `CLI:` equivalent.

## Pick the operation

| The user wants to… | MCP tool | CLI |
|---|---|---|
| start / resume work on a ticket | `grove_start(type, name, ticket, base?)` | `gwt start PROJ-1 feature "login"` |
| see the worktrees and their state | `grove_list` | `gwt list` |
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

## Everyday flow

- [ ] `grove_start` → note `path`, `mode` and `next_steps`
- [ ] work and commit inside `path`
- [ ] first push: `git push -u origin <branch>` (from `next_steps`)
- [ ] after the merge: `grove_remove(merged=true, dry_run=true)`, review, then
      `grove_remove(merged=true, delete_branch=true, confirm=true)`

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
- After upgrading grove, the MCP client must be **restarted** to load the new
  `grove-mcp`; new tools may also need a tool-list refresh.
- The command is **`gwt`** (also installed as `grove`); the PyPI package is
  `grove-wt`.
- grove never queries Jira/GitHub issues: ticket keys and names come from the
  user.

## When something goes wrong

Read [references/troubleshooting.md](references/troubleshooting.md) when a
grove command fails, `grove_doctor` reports something you don't recognize, git
refuses to open the repo, or an upgrade doesn't show up.

Read [references/configuration.md](references/configuration.md) when the user
wants to change the base branch, ticket rules, profiles or relative worktree
paths.
