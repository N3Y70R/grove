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
| worktrees look missing/prunable from a container | absolute paths from another machine | use `gitdir` from `grove_list`; never prune from there |
| "Repository not found" on push/fetch | wrong SSH key for the host | `grove_ssh_aliases`, `grove_ssh_check(live=true)`, `gwt config set-ssh-alias <alias>` |
| new version installed but not visible | MCP server still running the old code | restart the MCP client; refresh tools |
| `pipx install --force grove-wt` installs an older version | stale PyPI index on the network | `pipx runpip grove-wt index versions grove-wt`; or install from a local checkout |

`doctor` fixes run in a safe order (locks first) and never delete work: a
parking branch with its own commits, a dirty worktree or a recent lock is only
reported.
