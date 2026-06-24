# grove — Go implementation (🚧 planned)

Not implemented yet. This folder will hold the Go version of the `gwt` command, which must follow the same [specification](../spec/specification.md) and behave identically to the [Python](../python/) implementation.

## Planned layout

```
go/
├── go.mod            # module github.com/N3Y70R/grove/go
├── cmd/gwt/          # binary main
└── internal/
    ├── core/         # convention, validations, git wrappers (equivalent to python/src/grove/core)
    └── cli/          # flag parsing and presentation
```

## Notes

- **Module path:** since it's in a subfolder, it's `github.com/N3Y70R/grove/go`; releases use tags `go/vX.Y.Z`.
- **Parity:** it must pass the [`conformance/`](../conformance/) suite once it exists.
- Same output conventions as Python: `→ ✓ ! ✗` steps, the global `--json` flag with the same envelope, the same exit codes.
