# Design note — `gwt convert`: turn an existing clone into the grove model

**Status:** implemented in python 0.6.0 (`gwt convert` / `grove_convert`).
**Goal:** turn a normal local clone (`myrepo/` with `.git/` and one working tree)
into grove's bare + worktrees model **without re-cloning from the network**,
preserving the user's local branches, stashes and (by default) uncommitted work.

This complements `setup` (which clones fresh from a URL) and `track` (which
brings existing branches into an already-managed repo). `convert` is the missing
"take what I already have on disk and make it a grove repo" step.

## Target model (recap)

```
myrepo/
├── .bare/                     # the git repository (bare) + grove.toml
├── worktree-config-root       # parking branch (HEAD of .bare points here)
├── <base>/                    # worktree of the base branch (e.g. production)
└── <current-branch>/          # worktree of the branch you were on
```

## Decisions (fixed)

1. **In-place by default, with a safety net.** `gwt convert` converts the current
   repo folder in place. The original git data is **never deleted** — it is
   *moved* into `.bare/` — and a small restore manifest is written so the change
   is reversible. `--into <dir>` produces a **new** grove folder and leaves the
   source clone fully intact (see "Two modes").
2. **Auto-stash and restore.** If the working tree is dirty, grove runs
   `git stash push -u` (includes untracked) before the surgery and **pops** the
   stash inside the current-branch worktree afterwards. Nothing the user had is
   lost; a pop conflict is reported (never silently dropped).
3. **Materialize the current branch + the base branch.** By default `convert`
   creates two worktrees: the branch you were on and the repo's base branch
   (when it exists and differs). `--branches current` limits it to just the
   current one; `--branches all` materializes every local branch.
4. **Submodules and LFS are blocked in v1 (with a report), unless `--force`.**
   If grove detects submodules (`.gitmodules`) or Git LFS (`.gitattributes`
   `filter=lfs` or `.git/lfs/`), it **refuses** and explains why; `--force`
   proceeds at the user's risk. Full first-class support is deferred (a
   colleague's repos use these, so it's on the backlog — see "Future work").

## Two modes

### In-place (default) — preserves everything, including WIP

Reuses the existing `.git` (offline, fast, keeps all refs/branches/stashes/config):

1. **Preconditions:** `path` is a non-bare git repo; not already a grove repo
   (no `.bare/`); `HEAD` is on a branch (detached HEAD → error in v1). Capture:
   current branch, `origin` URL + remotes, and the base branch (reuse setup's
   origin-default detection; fall back to the active profile's base).
2. **Stash if dirty:** `git stash push -u -m "grove-convert"` (remember whether a
   stash was created).
3. **Convert to bare:** `mv .git .bare`; `git -C .bare config core.bare true`;
   ensure `remote.origin.fetch = +refs/heads/*:refs/remotes/origin/*` and
   `push.default = current`. (No network needed — the clone already has its
   `refs/remotes/origin/*`; `git fetch` is best-effort and can be skipped with
   `--no-fetch`.)
4. **Parking branch:** create `worktree-config-root` from the base and point
   `HEAD` at it (`symbolic-ref`).
5. **Clean the orphaned root checkout** (merged recursively, path by path — a
   tracked folder can also hold ignored files, e.g. `python/.venv`; a conflict is
   kept at the root and reported)**:** the old working-tree files now sit
   loose at the repo root; tracked ones are safe in git (they'll be recreated in
   a worktree) and untracked ones already traveled in the stash, so they are
   removed. `.bare/` and the restore manifest are never touched.
6. **Create worktrees:** for the current branch (folder = branch name, per the
   convention) and, per decision 3, for the base branch. Set upstreams when
   `origin/<branch>` exists.
7. **Restore WIP:** if a stash was created, `git stash pop` inside the
   current-branch worktree.
8. **Write `.bare/grove.toml`** (effective policy + detected base).

**Reversibility / safety net.** Before step 3, write `myrepo/.grove-convert-backup/`
with: the original `HEAD`, branch list, the stash ref, and a copy of
`.git/config`. Because `.git` is *moved* (not deleted), a botched run can be
undone by moving `.bare` back to `.git` and clearing `core.bare`. `--no-backup`
skips the manifest; the operation refuses if `.grove-convert-backup/` already
exists (previous run not cleaned up).

### `--into <dir>` — safest; source untouched

Builds a fresh grove structure from the **local** objects, leaving the original
clone completely untouched:

1. `git clone --bare <source-path> <dir>/.bare` (offline, copies all branches).
2. Read `origin` URL from the source and set it on the new `.bare` (+ refspec,
   `push.default`); optional `fetch` unless `--no-fetch`.
3. Parking branch + worktrees (current + base) + `grove.toml`, as above.

Trade-off (documented): because the source is untouched, **uncommitted/stashed
work is NOT carried over** in `--into` mode — it stays in the original clone. Use
in-place mode if you want your WIP migrated.

## Command surface

```
gwt convert [path] [--into <dir>] [--branches current|current+base|all]
                 [--no-fetch] [--no-backup] [--force] [--dry-run]
```

- `path` — the existing clone (default: current directory).
- `--into <dir>` — create a new grove repo there; leave the source intact.
- `--branches` — which worktrees to materialize (default: `current+base`).
- `--no-fetch` — don't contact origin (pure offline).
- `--force` — proceed even if submodules or Git LFS are detected (otherwise
  convert refuses; see decision 4).
- `--dry-run` — print the exact plan (moves, worktrees, stash) without doing it.

**MCP:** `grove_convert(path=None, into=None, branches="current+base",
fetch=True, force=False, dry_run=False, cwd=None)` — enriched per the project's
definition-of-done (per-parameter descriptions, `branches` as an enum,
annotations: not read-only, not destructive but mutating; `openWorldHint=false`).

`--dry-run` should be the default suggestion in docs/chat because convert
restructures a real repo.

## Preconditions & failure modes (v1)

- Not a git repo, or already a grove repo (`.bare/` present) → clear error.
- Detached `HEAD` → error (ask the user to check out a branch first).
- `--into` target exists and is non-empty → error.
- **Submodules** (`.gitmodules`) or **Git LFS** (`.gitattributes` `filter=lfs` or
  `.git/lfs/`) detected → refuse with a report explaining the risk; `--force`
  overrides. Detection runs before any change is made.
- Stash pop conflict after conversion → leave it for the user to resolve, report
  clearly (don't drop the stash).
- A merge/rebase in progress → refuse (state is ambiguous).

## What is preserved

| Thing | In-place | `--into` |
|---|---|---|
| Commit history / all local branches | ✅ | ✅ |
| Remotes & git config | ✅ | origin re-set from source |
| Stashes (existing) | ✅ (kept in `.bare`) | ❌ (stay in source) |
| Uncommitted + untracked (WIP) | ✅ (auto-stash → pop) | ❌ (stay in source) |
| Reflogs | ✅ | partial (fresh clone) |

## Testing plan

- In-place convert of a clean clone → `.bare/` + current & base worktrees; history intact.
- In-place convert with dirty tree (tracked + untracked) → WIP restored in the current worktree via stash pop.
- `--into` convert → new folder valid; source clone byte-for-byte untouched.
- `--branches all` → every local branch materialized.
- Error cases: detached HEAD, already-grove, non-repo, non-empty `--into`.
- Reversibility: after a (simulated) failure, `.bare`→`.git` restores the clone.

## Resolved: submodules & LFS (v1)

Both are **detected and blocked with a clear report, unless `--force`**:

- **Submodules** — moving `.git/modules/*` into `.bare` is mechanical, but each
  worktree needs `git submodule update --init` and submodules across worktrees
  are historically fragile, so v1 refuses by default to avoid leaving an
  inconsistent repo.
- **Git LFS** — refusing by default prevents the worst failure mode (a checkout
  full of LFS *pointer* files when git-lfs isn't installed/working). `--force`
  proceeds; worktrees share the object store, so with git-lfs installed it
  generally works.

Neither blocks the maintainer's own repos (they use neither), but a teammate's
repos do — hence the `--force` escape hatch now and full support later.

## Related: the root `.git` pointer

Both `setup` and `convert` create a **`.git` file at the repo root** containing
`gitdir: ./.bare` (relative, portable), so plain `git` works from the container
folder (`git worktree list`, `fetch`, `branch`, `log`) and IDEs/scripts that
expect a `.git` at the root behave. grove's own commands don't need it (they call
`git -C .bare …`), but it improves compatibility.

- **Default on**, disable with `--no-git-pointer` on `setup`/`convert`.
- Only created if a root `.git` doesn't already exist; never clobbers.
- Worktree subfolders already have their own `.git` file (into `.bare/worktrees/…`);
  this is only about the **root**.
- **Healing existing repos:** `doctor` gains a check **"missing root `.git`
  pointer"** that is **auto-fixable** (`gwt doctor --fix` writes it). This
  backfills repos created before this feature (or set up by hand without it).
  Quick manual equivalent at the repo root: `printf 'gitdir: ./.bare\n' > .git`.

## Future work

- First-class **submodule** support: initialize submodules per worktree on
  create/convert; verify the `.git/modules` layout works across worktrees.
- First-class **LFS** support: ensure smudge/checkout works and add a pre-flight
  check that git-lfs is installed; surface it in `doctor`.
