# Registering `grove-mcp` in an MCP client

`grove-mcp` is grove's MCP server: it exposes the worktree operations as tools
over **stdio** so an agent (Claude Desktop, Cursor, VS Code, etc.) can call
them. This guide covers installing it and wiring it into the common clients.

For the tool list and design, see [`../python/src/grove/mcp/README.md`](../python/src/grove/mcp/README.md)
and the spec ([§13](../spec/specification.md)).

## 1. Install (with the `mcp` extra)

The MCP SDK is an optional extra; install grove so that the `grove-mcp`
executable lands on your `PATH`. **pipx** is the cleanest option:

```bash
# from the published GitHub repo (PEP 508 extra + git URL):
pipx install "grove[mcp] @ git+https://github.com/N3Y70R/grove.git#subdirectory=python"

# or from a local checkout:
pipx install "./python[mcp]"
```

(Plain `pip install "grove[mcp]"` also works inside a virtualenv; pipx just
keeps it isolated and on your PATH.)

Verify and note the absolute path — some clients don't inherit your shell PATH,
so using the full path in the config is the most reliable:

```bash
grove-mcp --help 2>/dev/null; which grove-mcp
# e.g. /Users/you/.local/bin/grove-mcp
```

## 2. A note on the working directory

grove operates on a **managed repo** (a folder containing `.bare/`). Every tool
accepts an optional `cwd` argument pointing at that repo (or, for `grove_setup`,
the parent folder where the repo will be created). When you talk to the agent,
just mention the repo path and it will pass `cwd`; you don't configure a working
directory in the client. Example asks:

- "Use grove to list the worktrees in `/Users/you/code/myrepo`."
- "Create a feature worktree for PROJ-123 'login fix' in `/Users/you/code/myrepo`."

## 3. Claude Desktop

Config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/claude-desktop/claude_desktop_config.json`

You can also open it from **Settings → Developer → Edit Config**. Add a `grove`
entry under `mcpServers` (use the absolute path from step 1):

```json
{
  "mcpServers": {
    "grove": {
      "command": "/Users/you/.local/bin/grove-mcp",
      "args": []
    }
  }
}
```

Save and **restart Claude Desktop**. grove's tools then appear in the tools
list (the 🔌/hammer icon).

## 4. Cursor

Config file: `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global).
Same `mcpServers` shape:

```json
{
  "mcpServers": {
    "grove": {
      "command": "/Users/you/.local/bin/grove-mcp",
      "args": []
    }
  }
}
```

Enable it in **Cursor Settings → MCP**.

## 5. VS Code (Copilot agent mode)

VS Code uses a slightly different schema (`servers` + explicit `type`). Config
file: `.vscode/mcp.json` (workspace) or your user `mcp.json`:

```json
{
  "servers": {
    "grove": {
      "type": "stdio",
      "command": "/Users/you/.local/bin/grove-mcp",
      "args": []
    }
  }
}
```

## 6. Any stdio MCP client (generic)

Launch command:

```bash
grove-mcp          # or:  python -m grove.mcp
```

It speaks MCP over stdin/stdout. Point the client's "command" at `grove-mcp`
(absolute path recommended) with no arguments.

## 7. Available tools

Worktree & config: `grove_setup`, `grove_list`, `grove_create`, `grove_track`,
`grove_remove`, `grove_sync`, `grove_publish`, `grove_doctor`, `grove_compare`,
`grove_config`, `grove_ssh_check`.

SSH account provisioning (machine-level; see USAGE §`gwt ssh add …`):
`grove_ssh_add`, `grove_ssh_accounts`, `grove_ssh_doctor`, `grove_ssh_remove`.

Destructive tools (`grove_remove`, `grove_sync`, `grove_publish` with
`regenerate`, and `grove_ssh_remove`) require a `confirm: true` argument; the
agent must pass it explicitly, which is your safety gate.

grove never touches the network or any ticket system: ticket keys/slugs are
passed in as parameters. To enrich (e.g. fetch a Jira/GitHub issue title), the
agent uses its own connector and then calls `grove_create` with the resolved
data. The same applies to `grove_ssh_add`: grove provisions locally and returns
the public key; the **agent uploads it** to GitHub/Bitbucket via its own connector.

## 8. Troubleshooting

- **"command not found" / server fails to start:** the client isn't seeing
  `grove-mcp` on PATH — use the absolute path from `which grove-mcp`.
- **"The MCP SDK is not installed":** you installed grove without the extra.
  Reinstall with `[mcp]` (step 1).
- **Tools don't appear:** restart the client after editing its config; check the
  client's MCP logs.
- **"No managed repo (.bare/) found":** the tool needs the repo path — ask the
  agent again including the absolute path so it passes `cwd`.

## 9. Conversational flows (chat → grove tools)

Examples of what to type in chat and which tool/arguments the agent should use.
Always mention the repo path so the agent passes `cwd`.

### Set up a repo (incl. non-standard base branch)

> "Set up grove for `git@github.com:org/app.git` under `/Users/me/code`,
> base branch `production`, using my `work-gh` SSH alias."

→ `grove_setup(url=…, into="/Users/me/code", ssh_alias="work-gh")`. If the repo's
default branch isn't `main`, **say the base explicitly** (e.g. "production") or
pick a profile whose `default_base` matches; otherwise grove uses the profile
default. Tip: "use the `gitflow` profile" or "base branch is production".

### Work a ticket (create a worktree)

> "Create a feature worktree for PROJ-123 'login bug' in `/Users/me/code/app`."

→ `grove_create(kind="ticket", type="feature", name="login bug", ticket="PROJ-123", cwd=…)`.

### Create a worktree from a SPECIFIC base branch

> "Create a temp worktree `spike-cache` **from branch `release/v2`** in
> `/Users/me/code/app`."

→ `grove_create(kind="temp", name="spike-cache", base="release/v2", cwd=…)`.
The key is the word **"from `<branch>`"** → it maps to the `base` argument. The
same `base` works for `kind="ticket"` and `kind="release"`.

### See status / list

> "List grove worktrees in `/Users/me/code/app`." → `grove_list(cwd=…)`
> "Which ones are dirty?" → `grove_list(cwd=…, dirty=true)`
> "How far ahead/behind is `feature/PROJ-123` vs `production`?"
> → `grove_compare(a="feature/PROJ-123", b="production", cwd=…)`

### Bring in an existing branch

> "Track the existing branch `hotfix/PROJ-9-fix` in `/Users/me/code/app`."
> → `grove_track(branch="hotfix/PROJ-9-fix", cwd=…)`

### Publish to the shared integration branch

> "Publish `PROJ-123` to the integration branch in `/Users/me/code/app`."
> → `grove_publish(targets=["PROJ-123"], cwd=…)`
> "Rebuild integration from `production` with PROJ-1 and PROJ-2."
> → `grove_publish(targets=["PROJ-1","PROJ-2"], regenerate=true, base="production", confirm=true, cwd=…)`
> (rebuilding an **existing** branch force-pushes → the agent must pass `confirm=true`).

### Create or recreate the integration branch from a base

The same tool both **creates** the branch (if missing) and **rebuilds** it (if it
exists). Say "from `<branch>`" → `base`, and name the branch with `into`.

> "Create the `temporary-unified-test` integration branch from `production` in
> `/Users/me/code/app`." (first time, empty) →
> `grove_publish(targets=[], into="temporary-unified-test", regenerate=true, base="production", cwd=…)`
> — created fresh → normal push, **no confirm needed**.

> "Recreate `temporary-unified-test` from `production` including PROJ-1." →
> `grove_publish(targets=["PROJ-1"], into="temporary-unified-test", regenerate=true, base="production", confirm=true, cwd=…)`
> — if it already exists this force-pushes, so pass `confirm=true`.

The result includes `created: true/false` and `mode` (`created` | `regenerate` |
`additive`) so the agent can tell which happened.

### Re-sync / clean up (destructive → need confirmation)

> "Re-sync the integration worktree with origin (discard local), in `…/app`."
> → `grove_sync(target="temporary-unified-test", confirm=true, cwd=…)`
> "Remove the `PROJ-123` worktree and its branch." →
> `grove_remove(target="PROJ-123", delete_branch=true, confirm=true, cwd=…)`
> "Sweep all worktrees already merged into the base." →
> `grove_remove(merged=true, confirm=true, cwd=…)`

### SSH accounts (machine-level — no `cwd`)

> "Diagnose my SSH/git setup and fix what's safe." → `grove_ssh_doctor(fix=true)`
> "List my grove-managed SSH accounts." → `grove_ssh_accounts()`
> "Provision a `work-gh` account for github.com, email me@org.com, scoped to
> `/Users/me/work`." →
> `grove_ssh_add(name="work-gh", host="github.com", email="me@org.com", scope_dir="/Users/me/work")`
> (grove prints the public key; the agent uploads it via its own GitHub/Bitbucket connector).

### Phrasing tips that avoid friction

- To branch off something other than the repo default, say **"from `<branch>`"**
  — it maps to `base`.
- If the repo uses a non-standard base (e.g. `production`), state it on setup or
  choose a matching profile; don't assume `main`.
- For destructive actions, expect the agent to ask for / pass `confirm=true`.
