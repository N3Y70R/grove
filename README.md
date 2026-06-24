# grove

**grove** manages git worktrees with a consistent convention and structure. The command is called **`gwt`** (git worktree).

This repository is a **monorepo**: the same tool implemented in several languages, all following a single [specification](spec/specification.md).

## Design principle

grove does **one thing**: manage worktrees and their git convention. It **does not query** Jira, Linear, GitHub Issues or any platform — the ticket key and descriptions arrive **by parameter**. This keeps the core pure, offline, platform-agnostic and easy to keep identical across languages. Integration with external systems lives in the orchestration layer (a script or the agent via MCP). Details in the [spec](spec/specification.md#design-principles).

## Implementations

| Language | Folder | Status |
|---|---|---|
| Python | [`python/`](python/) | ✅ functional (reference) |
| Go | [`go/`](go/) | 🚧 planned |
| Rust | [`rust/`](rust/) | 🚧 planned |

All implementations expose the same `gwt` command and must behave the same according to the spec.

## Documentation (shared)

- **[docs/TUTORIAL.md](docs/TUTORIAL.md)** — hands-on guide with full workflows and diagrams. Start here.
- **[docs/USAGE.md](docs/USAGE.md)** — reference for each command, flags and configuration.
- **[docs/INSTALL.md](docs/INSTALL.md)** — installation, updating and troubleshooting.
- **[spec/specification.md](spec/specification.md)** — design and behavior contract (source of truth).

## Repository structure

```
grove/
├── docs/           # shared documentation (tutorial, usage, install)
├── spec/           # the specification, language-agnostic
├── conformance/    # (future) black-box tests to validate any implementation
├── python/         # Python implementation
├── go/             # Go implementation (planned)
└── rust/           # Rust implementation (planned)
```

## Versioning

Each implementation is versioned independently with language-prefixed tags: `python/vX.Y.Z`, `go/vX.Y.Z`, `rust/vX.Y.Z`.

## License

[GNU GPL-3.0](LICENSE).
