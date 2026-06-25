# How to contribute to grove

Thanks for your interest. grove is a **monorepo** with the same tool (`gwt`) in several languages; all implementations follow a single [specification](spec/specification.md).

## Principles

- **The spec rules.** Any behavior change is discussed and documented first in `spec/specification.md`. Implementations follow it, not the other way around.
- **Parity across languages.** Python, Go and Rust must behave the same (same folder structure, same branch names, same `--json` envelope, same exit codes). Once the [`conformance/`](conformance/) suite exists, every implementation must pass it.
- **Shared docs.** The tutorial, the usage guide and the installation guide live in `docs/` and apply to all implementations.

## Structure

```
docs/   spec/   conformance/   python/   go/   rust/
```

Work inside the folder for the language you touch. Each implementation has its own README with how to build and test.

## Workflow

1. Open an issue describing the change (or comment on an existing one).
2. Create a branch per topic.
3. Make commits following the convention below.
4. Make sure the implementation you touched compiles and passes its tests (and the CI smoke test).
5. Open a Pull Request.

## Definition of done (every behavior change)

A change that adds or modifies a command/operation isn't done until **all four
facades and docs stay in sync**:

1. **core** — the logic, with unit/integration tests.
2. **CLI** (`grove.cli`) — flags/args wired to the core.
3. **MCP** (`grove.mcp`) — the tool exposed *and enriched*:
   - every parameter has a **`Field(description=…)`**;
   - constrained choices use an **enum** (`Literal[...]`);
   - the tool has **`ToolAnnotations`** (read-only / destructive / idempotent,
     `openWorldHint=False`).
   `tests/test_mcp_schema.py` enforces this (it fails if any parameter lacks a
   description). The MCP is the agent's only view of the tool, so poor schemas =
   poor discoverability.
4. **docs** — `USAGE.md` (reference), `TUTORIAL.md` (flow if relevant), and
   `MCP.md` §9 (conversational example: CLI + tool call + chat phrasing), plus a
   `CHANGELOG.md` entry.

## Commit message convention

The grove standard combines **Conventional Commits** (in the title, to automate changelog/semver) with the **What / Why** discipline in the body (so the log makes sense months later). Structure:

```
<type>(<scope>): <imperative summary>            # title, ≤72

What: <what changes technically>                # one line, target ≤100
Why:  <why it is done>                           # one line; can extend if needed

<optional paragraph: extra context, wrapped at ~72>

<optional footer: Refs / BREAKING CHANGE>
```

### Title

`<type>(<scope>): <summary>`

**Allowed types:**

| Type | For |
|---|---|
| `feat` | a new feature |
| `fix` | a bug fix |
| `docs` | documentation only |
| `refactor` | internal change without altering behavior |
| `test` | adding or adjusting tests |
| `perf` | performance improvement |
| `build` | packaging, dependencies, build |
| `ci` | CI configuration |
| `chore` | miscellaneous tasks (don't affect src or tests) |
| `style` | formatting (spaces, commas), no logic |
| `revert` | reverts a previous commit |

- **Scope (optional):** the affected area, e.g. `python`, `go`, `rust`, `cli`, `core`, `spec`, `docs`, `conformance`.
- **Summary:** imperative and lowercase ("add", "fix", not "added"/"adding"), no trailing period, ≤72 characters total.

### Body (`What` / `Why`)

- **`What:`** explains WHAT changes technically. One concise line; target ≤100 characters (a guide, not a wall).
- **`Why:`** explains WHY it is done. Ideally one line, **with no hard cap**: if the reason needs more, continue on lines wrapped at ~72.
- `What` and `Why` must say **different** things (don't repeat the title or repeat each other).
- For complex changes you can add a **context paragraph** after the `Why` (wrapped at ~72): the `What`/`Why` are the summary, the paragraph is the long explanation.
- **Required** for `feat`, `fix`, `refactor`, `perf`. Optional for trivial changes (minor `docs`, `chore`, `style`, `test`).

### Footer (optional)

- **`Tags: <tag>, <tag>`** cross-cutting labels for search (see vocabulary below).
- **`Refs: #<issue>`** to link the GitHub issue.
- **`BREAKING CHANGE: <description>`** for incompatible changes (additionally, add `!` after the type/scope in the title).

### Vocabulary: scopes and tags

So that commits are easy to find (grep, tools, AI), we use a **controlled but soft** vocabulary: this is an initial list, extensible via PR; for now it is convention (it is not validated automatically). Stay consistent: reuse an existing term before inventing a new one.

**Scopes** (the area of the repo or the CLI that the change touches; one per commit):

- Structure: `python`, `go`, `rust`, `docs`, `spec`, `conformance`, `ci`, `build`, `repo`
- Components: `cli`, `core`
- Commands: `setup`, `create`, `track`, `remove`, `sync`, `publish`, `doctor`, `list`, `config`, `ssh`

**Tags** (`Tags:` in the footer; cross-cutting labels that don't fit as a scope, comma-separated):

- `breaking` — incompatible change
- `security` — security-relevant (keys, credentials)
- `performance` — performance
- `ux` — usage experience / output / messages
- `migration` — requires migrating existing config or data
- `dependencies` — dependencies / packaging
- `tech-debt` — cleanup / technical debt

**How to search:**

```
git log --grep '^feat'                                  # by type
git log --grep '(ssh)'                                  # by scope
git log --grep 'Tags:.*security'                        # by tag
git log --format='%H %s %(trailers:key=Tags,valueonly)' # extract tags (scripts/AI)
```

> To add a new scope or tag, add it to these lists in the same PR that introduces it.

### Inherited rules (team discipline)

- **Never** AI attribution in the message (`Generated with…`, `Co-Authored-By: …`).
- **Never** commit secrets or artifacts (`.env`, keys, `dist/`, `build/`, `node_modules/`…).
- **Multi-commit per domain:** if the changes cover distinct topics, split them into several coherent commits instead of one big one.
- To commit, use a **heredoc** to preserve line breaks:

  ```bash
  git commit -m "$(cat <<'EOF'
  feat(cli): add global --json envelope with status and reason

  What: every command emits {status, exit_code, message, result, log}.
  Why: exit codes alone were ambiguous for scripts and CI.

  Refs: #12
  EOF
  )"
  ```

### Examples

```
feat(cli): add global --json envelope with status and reason

What: every command emits {status, exit_code, message, result, log}.
Why: exit codes alone were ambiguous for scripts and CI.

Tags: ux
Refs: #12
```

```
fix(core): avoid false ticket match on branches without a key

What: extract_ticket now returns None when no key is present.
Why: branches like feature/cleanup were misread as tickets.
```

```
refactor(core)!: set upstream from the bare instead of by path

What: upstream is configured via `git -C .bare branch --set-upstream-to`.
Why: a worktree move could break a path-based upstream update.

BREAKING CHANGE: scripts that relied on the old path-based behavior must adapt.
```

```
docs(tutorial): add multi-account SSH flow
```

### Local commit template

The repo includes a template in `.gitmessage`. Enable it so your editor shows it when committing:

```
git config commit.template .gitmessage
```

## Releases

Each implementation is versioned separately with language-prefixed tags: `python/vX.Y.Z`, `go/vX.Y.Z`, `rust/vX.Y.Z`. Changes are recorded in [`CHANGELOG.md`](CHANGELOG.md).

## License

By contributing, you agree that your contribution is published under the [GPL-3.0](LICENSE).
