# grove configuration

Per-repo policy lives in `.bare/grove.toml`; inspect it with `grove_config`
(or `gwt config`). Change one key with
`grove_config(set_key=…, set_value=…)` / `gwt config set <key> <value>`;
remove it (falls back to the repo's profile) with `unset_key` / `gwt config unset`.

| Key | Meaning |
|---|---|
| `default_base` | base for new worktrees (e.g. `main`, `production`) |
| `allowed_types` | ticket types `create`/`start` accept (comma-separated) |
| `tickets` | `required`, `optional` or `off` |
| `ticket_prefixes` | accepted keys, e.g. `PROJ,OPS` (recommended when using tickets) |
| `integration_branch` | shared branch for `publish` |
| `ssh_alias` | set with `set_ssh_alias`, which also rewrites `origin` |
| `relative_worktrees` | `true` = relative worktree paths (git >= 2.48 everywhere!) |

- **Profiles** are templates applied at `setup`/`convert` (`profile=`):
  built-in `default`, `personal`, `gitflow`, or `[profiles.<name>]` in
  `~/.config/grove/config.toml`. Editing a profile does not change existing
  repos; only unset keys fall back to it.
- A different base for one worktree doesn't need config: pass `base=` to
  `grove_start` / `grove_create`.
