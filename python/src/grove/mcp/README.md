# grove.mcp — MCP facade

The **MCP server** (Model Context Protocol) of the Python implementation:
grove's worktree operations exposed as *tools* for an agent (Claude/Cowork)
to invoke. It is a thin facade over `grove.core`, exactly like `grove.cli`.
Full design in [`../../../../spec/specification.md`](../../../../spec/specification.md) (§13).

```
grove.core
 ├── grove.cli   → gwt command
 └── grove.mcp   → MCP server (this package)
```

## Layout

```
mcp/
├── __init__.py
├── __main__.py     # python -m grove.mcp
├── _ops.py         # pure operation layer: returns the structured result (no SDK import)
└── server.py       # FastMCP tools over _ops; starts the server (stdio)
```

`_ops.py` has **no MCP SDK dependency**, so the operation logic is importable
and unit-testable on its own; `server.py` only wraps each function as a tool.

## Tools

≈1:1 with the commands, with typed inputs and structured output:

| Tool | Notes |
|------|-------|
| `grove_setup` | initialize a repo (profile, optional `ssh_alias`) |
| `grove_list` | filters: `type`, `dirty`, `orphans` |
| `grove_create` | `kind` = `ticket` (default) \| `release` \| `temp` |
| `grove_track` | `as_` for an explicit destination |
| `grove_remove` | **destructive** → `confirm=true` (or `merged` sweep) |
| `grove_sync` | **destructive** (reset --hard) → `confirm=true` |
| `grove_publish` | additive; `regenerate` force-push → `confirm=true` |
| `grove_doctor` | `fix=true` applies auto-fixable issues |
| `grove_compare` | read-only ahead/behind (`a`/`b` or `vs`) |
| `grove_config` | show, or set the SSH alias (`set_ssh_alias`) |
| `grove_ssh_check` | SSH diagnostics for the remote |

Differences from the CLI: typed inputs (JSON schema) instead of text flags;
no interaction (destructive actions confirm via a boolean parameter); output
is always the structured `result`, never human text.

Every tool takes an optional `cwd` to locate the managed repo (defaults to the
process working directory).

## No network / no ticket clients

Per the design principle, the MCP facade does **not** go out to the network and
has no Jira/Linear/GitHub-issue clients. Ticket keys and slugs arrive **by
parameter**. Enrichment (e.g. fetching an issue title, then calling
`grove_create` with the resolved data) is the agent's job, composing its own
connectors with these tools.

## Install & run

```
pip install "grove[mcp]"   # base CLI stays dependency-free; SDK is an extra
grove-mcp                  # starts the server over stdio
# or
python -m grove.mcp
```

Register it with an MCP-capable client (stdio transport) by pointing the
command at `grove-mcp`.

## Versioning & parity

Versioned with the Python implementation (`python/vX.Y.Z`). It must behave the
same as the CLI per the spec; in the future the
[`conformance/`](../../../../conformance/) suite can also validate this layer.
