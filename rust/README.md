# grove — Rust implementation (🚧 planned)

Not implemented yet. This folder will hold the Rust version of the `gwt` command, which must follow the same [specification](../spec/specification.md) and behave identically to the [Python](../python/) implementation.

## Planned layout

```
rust/
├── Cargo.toml        # name = "grove", binary "gwt"
└── src/
    ├── main.rs       # CLI entry point
    ├── core/         # convention, validations, git wrappers
    └── cli/          # argument parsing and presentation
```

## Notes

- **Releases:** tags `rust/vX.Y.Z`. Publishing to crates.io (if done) comes from this subfolder.
- **Parity:** it must pass the [`conformance/`](../conformance/) suite once it exists.
- Same output conventions as Python: `→ ✓ ! ✗` steps, the global `--json` flag with the same envelope, the same exit codes.
