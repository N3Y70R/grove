# grove.mcp — MCP facade (🚧 placeholder, not implemented)

This folder will hold the **MCP server** (Model Context Protocol) of the Python implementation: grove's operations exposed as *tools* for an agent (Claude/Cowork) to invoke. Today it's just a placeholder; the full design is in [`../../../../spec/specification.md`](../../../../spec/specification.md) (§13).

## Idea

The MCP is **another thin facade over `grove.core`**, just like `grove.cli`:

```
grove.core
 ├── grove.cli   → gwt command
 └── grove.mcp   → MCP server (this package)
```

It reuses what already exists:

- The structured `result` of `--json` is what each tool will return.
- Destructive operations already confirm by parameter (not by prompt), so they fit an agent without changes.

## Planned tools

≈1:1 mapping with the commands: `grove_setup`, `grove_list`, `grove_create`, `grove_track`, `grove_remove`, `grove_sync`, `grove_publish`, `grove_doctor`, `grove_config`, `grove_ssh_check` — with typed inputs, confirmation by parameter and structured output. Later, enrichment tools (e.g. `grove_create_from_issue`).

## Planned layout

```
mcp/
├── __init__.py
└── server.py        # registers the tools over grove.core and starts the server (stdio)
```

## Planned packaging

- MCP SDK as an **optional dependency**: `pip install "grove[mcp]"` (the base CLI stays dependency-free).
- A `grove-mcp` entry point in `pyproject.toml`, in addition to `gwt`.
- Versioned with the Python implementation (`python/vX.Y.Z`).

## Status

Nothing implemented yet. When developed, it must behave the same as the CLI per the spec (and, in the future, pass the [`conformance/`](../../../../conformance/) suite).
