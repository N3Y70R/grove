# grove troubleshooting

Match the symptom, apply the fix, re-run `grove_doctor` to confirm.

| Symptom | Cause | Fix |
|---|---|---|
| "Another git process seems to be running" | orphaned `*.lock` in `.bare/` | `grove_doctor`; when the issue is `stale-lock`, `grove_doctor(fix=true)` |
| `lock` issue (not `stale-lock`) | lock is recent: git may be running | wait, re-run `grove_doctor` |
| "Author identity unknown" / `identity` issue | no `user.email` resolves for that folder | set `git config user.email`, or a zone with `gwt ssh add … --scope-dir` |
| "Base branch 'X' does not exist" | wrong `--base`, or outdated `default_base` | use a listed candidate, or `gwt config set default_base <branch>` |
| setup: "already exists and is a git clone" | the repo is already cloned | `grove_convert(path, dry_run=true)`, then without `dry_run` |
| "unknown repository extension: relativeworktrees" | `relative_worktrees` on, git < 2.48 | upgrade git, or with a new git: `gwt config set relative_worktrees false` |
| `bare-head` / `parking-branch` issues | repo made before grove 0.10.0 | `grove_doctor(fix=true)` (keeps a parking branch that has its own commits) |
| worktrees look missing/prunable from a container / VM, or git says "not a git repository" inside one | the worktree's `.git` holds an absolute path of the other machine | `GIT_DIR=<repo>/<gitdir> GIT_WORK_TREE=<repo>/<rel_path> git …` with `gitdir` / `rel_path` from `grove_list`; never `git worktree prune` from there (it would unregister them). Long term: `relative_worktrees` (see configuration) |
| "Repository not found" on push/fetch | wrong SSH key for the host | `grove_ssh_aliases`, `grove_ssh_check(live=true)`, `gwt config set-ssh-alias <alias>` |
| push rejected: `GH013` … "Commits must have verified signatures" | the remote requires signed commits | use `gwt signing doctor --error-file FILE --test -C WORKTREE`; see [signing](signing.md). Configure an explicit key/account with `signing enable` if needed. Re-signing old commits rewrites history: review branch ownership and obtain the user's instruction before rebasing/force-pushing |
| push rejected `(non-fast-forward)` right after a rebase | origin still has the pre-rebase commits | your own branch: `git push --force-with-lease`; if someone else pushed, `git pull --rebase` first |
| force-push refused by repository rules (`GH013`, "Cannot force-push") | rules forbid rewriting that branch | review the repository rules and use a merge when rewriting is forbidden; deleting a remote branch is not an automatic workaround |
| is the installed skill current? (no repo yet) | `grove_doctor` needs a managed repo | `grove_skill_status` / `gwt skill status`: version, `outdated`, `edited` for `~/.agents/skills` and `~/.claude/skills` |
| `skill-edited` issue | the installed skill was changed after `gwt skill install` | nothing to do if it was on purpose; `gwt skill install [--claude] --force` restores grove's copy. `gwt skill install --dry-run` shows which files differ |
| `skill-outdated` issue | installed skill written for another grove version | untouched copy: `grove_doctor(fix=true)`; edited: review, then `gwt skill install [--claude] --force` |
| new version installed but not visible, or a tool fails with "grove was upgraded to X, but this MCP server is still running Y" (older servers: a bare "Error executing tool") | MCP server still running the old code after an upgrade | restart the MCP client; refresh tools |
| `pipx install --force grove-wt` installs an older version | stale PyPI index on the network | `pipx runpip grove-wt index versions grove-wt`; or install from a local checkout |

`doctor` fixes run in a safe order (locks first) and never delete work: a
parking branch with its own commits, a dirty worktree or a recent lock is only
reported.

SSH doctor uses `remaining_findings` and `failures` to show unfinished repairs.
`agent` repair failed: unlock/load the existing key in a terminal and diagnose
again. `missing-identity`: restore the included file from a reviewed backup.
`effective-config`: inspect preceding manual Host/Include/Match rules; Grove
reports their effect without editing them. A concurrent edit error keeps the
other writer's change; reread the file before retrying.
