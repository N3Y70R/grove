# Conformance — parity tests across implementations

> **Status: 🚧 pending implementation.** This folder documents the plan; the harness and scenarios are built once a second implementation exists (Go or Rust). Until then, this is the specification of the suite itself.

## 1. Goal

Ensure that **all implementations of `gwt`** (Python, Go, Rust) are **interchangeable**: given the same inputs they produce the same observable behavior. The suite is **black box**: it does not know the code, it only runs the `gwt` binary it is told to and compares results against what the [specification](../spec/specification.md) expects.

Benefits:

- The spec stops being just a document and becomes **verifiable**.
- Any new implementation "is ready" when it passes the suite.
- Parity regressions are caught in CI.

## 2. What is verified

For each scenario, three observable things are compared (not internal details):

1. **`--json` output**: the full envelope (`status`, `exit_code`, `message` when applicable, and `result`). It is the primary comparison source because it is structured and stable.
2. **Exit code** of the process.
3. **State of the repository on disk** after the command: folder structure (worktrees created at their conventional path), branch names, and —when relevant— the configured `upstream` and the `origin`.

Comparing on `--json` avoids false negatives caused by formatting differences in the human-readable text (which may vary between languages); the human text is not compared.

## 3. Normalization (for stable comparisons)

Before comparing, whatever is legitimately variable across runs/languages is normalized:

- **Absolute paths** → relative to the root of the test repo (or replaced by a placeholder like `<REPO>`).
- **The `log` field** of the envelope is ignored by default (it is informative and its wording may differ); `status`, `exit_code`, `result` and, optionally, `error_type` are compared.
- **Commit SHAs** and timestamps → placeholders.
- Ordering of lists that have no guaranteed order (e.g. `list`) → sorted before comparing.

Each scenario can declare which fields are significant so as not to couple to irrelevant details.

## 4. Scenario format (proposal)

Declarative scenarios in YAML/JSON. Each one defines a minimal setup, a sequence of commands and the assertions. Draft:

```yaml
name: create-ticket-required
description: in required mode, create builds folder and branch with the convention
profile: gitflow               # profile used for setup (tickets required)
origin:                        # how to build the local test git origin
  branches: [main]
  default: main
steps:
  - run: ["setup", "$ORIGIN", "--name", "repo"]
  - cd: repo
  - run: ["create", "PROJ-1", "feature", "login", "--json"]
    expect:
      status: ok
      exit_code: 0
      result:
        rel_path: "feature/PROJ-1-login"
        branch: "feature/PROJ-1-login"
  - assert_tree:               # expected structure on disk
      - "feature/PROJ-1-login/"
      - "main/"
  - assert_branch:
      worktree: "feature/PROJ-1-login"
      name: "feature/PROJ-1-login"
```

Error scenario (the reason and the code matter, the text does not):

```yaml
name: create-invalid-type
steps:
  - run: ["setup", "$ORIGIN", "--name", "repo"]
  - cd: repo
  - run: ["create", "PROJ-1", "chore", "x", "--json"]
    expect:
      status: error
      exit_code: 1
      error_type: ValidationError
```

## 5. Runner design

A language-agnostic *runner*:

1. Receives the path of the binary to test via the environment variable **`GWT_BIN`** (e.g. the installed Python `gwt`, or the compiled Go/Rust binary).
2. For each scenario: creates a temporary directory, builds the described **local git origin** (`git init --bare` + seeded branches), exports `$ORIGIN` as `file://…`.
3. Runs the `steps` with `GWT_BIN`, captures stdout/exit code.
4. Normalizes (§3) and compares against `expect`/`assert_*`.
5. Reports PASS/FAIL per scenario and a summary.

The runner can be written in any language; the natural choice is a script (bash + jq, or Python with the stdlib) since it only runs processes and compares JSON. It must **not** depend on any of the implementations.

## 6. Planned layout

```
conformance/
├── README.md            # this document
├── run                  # executable runner: GWT_BIN=... ./run [scenarios/*]
├── lib/                 # helpers (build origin, normalize, compare)
└── scenarios/
    ├── setup/
    ├── create/
    ├── track/
    ├── remove/
    ├── sync/
    ├── publish/
    ├── doctor/
    ├── list/
    └── config/
```

## 7. CI integration

A workflow per implementation installs/compiles its binary and then:

```
GWT_BIN="$(command -v gwt)" ./conformance/run
```

This way each PR that touches `python/`, `go/` or `rust/` validates that the implementation still complies with the spec. (The Python workflow in `.github/workflows/python.yml` currently only does a *smoke test*; once the suite exists, the conformance run is added to it.)

## 8. How to add a case

1. Create a `.yaml` in `scenarios/<command>/`.
2. Describe `origin`, `steps` and `expect`/`assert_*`.
3. Run `GWT_BIN=$(command -v gwt) ./run scenarios/<command>/<case>.yaml` against the reference implementation (Python) and adjust until it passes.
4. That same case stays as a contract for Go and Rust.

## 9. To-do checklist

- [ ] Define the final scenario schema (significant fields, normalization).
- [ ] Write the runner (`run` + `lib/`), language-agnostic.
- [ ] Helper to build the test git origin (branches, releases, non-conventional branches).
- [ ] Scenarios per command:
  - [ ] `setup` (bare, parking branch, production tracking origin; with/without `--ssh-alias`)
  - [ ] `create` ticket in `required` / `optional` / `off` modes; new and existing release; temp
  - [ ] `track` conformant and with `--as`; special branches
  - [ ] `remove` individual, `--delete-branch`, `--merged`, protections, `--dry-run`
  - [ ] `sync` (reset to origin; confirmation guards in `--json`)
  - [ ] `publish` additive and `--regenerate`; conflict that aborts cleanly
  - [ ] `doctor` detection + `--fix` (orphans, release-format, naming, upstream, ticket mismatch)
  - [ ] `list` (classification and state)
  - [ ] `config` (show `--json`, `set-ssh-alias`)
  - [ ] `tickets` policy and `ticket_prefixes`
- [ ] Error cases with `error_type`/`exit_code` for each validation in the spec.
- [ ] Connect the suite to the CI of each implementation.
- [ ] Validate the reference implementation (Python) against the suite and pin it as baseline.
