# Installing grove (`gwt`)

grove is a command-line tool written in pure Python. You install it once and the `gwt` command becomes available in your terminal, on Windows, macOS, and Linux.

> **Name note:** the install/distribution name is **`grove-wt`** (the name
> `grove` was already taken on PyPI). The imported package is still `grove` and
> the commands are still **`gwt`** and **`grove-mcp`** — only the label you type
> in `pip`/`pipx` is `grove-wt`.

> **TL;DR:** with Python 3.11+ and `pipx` installed:
> ```
> pipx install grove-wt          # from PyPI (or: grove-wt[mcp] for the MCP server)
> gwt --version
> ```

---

## 1. Prerequisites

| Requirement | What for | How to verify |
|---|---|---|
| **Python 3.11+** | grove uses `tomllib` (stdlib in 3.11) | `python3 --version` |
| **git** | grove wraps `git worktree` | `git --version` |
| **pipx** (recommended) | installs the CLI in isolation and puts it on the PATH | `pipx --version` |

### 1.1 Install Python 3.11+

- **macOS:** `brew install python@3.12`
- **Debian/Ubuntu:** `sudo apt install python3.12`
- **Windows:** download from [python.org](https://www.python.org/downloads/) or `winget install Python.Python.3.12`. Check **"Add Python to PATH"** during installation.

Verify: `python3 --version` (on Windows it may be `py --version`) should show 3.11 or higher.

### 1.2 Install pipx

- **macOS:** `brew install pipx && pipx ensurepath`
- **Debian/Ubuntu:** `sudo apt install pipx && pipx ensurepath`
- **Windows:** `py -m pip install --user pipx` and then `py -m pipx ensurepath`
- **Any OS (alternative):** `python3 -m pip install --user pipx && python3 -m pipx ensurepath`

After `pipx ensurepath`, **close and reopen the terminal** so the PATH is updated.

> Why pipx and not `pip install`? pipx installs the tool in its own isolated environment, avoids conflicts with other packages, and exposes the `gwt` command globally. It's the recommended way to install Python command-line applications.

---

## 2. Installation options

### Option A0 — From PyPI (simplest, recommended)

```
pipx install grove-wt            # CLI only
pipx install "grove-wt[mcp]"     # CLI + the grove-mcp MCP server
gwt --version
```

Update later with `pipx upgrade grove-wt`. (If you also want the MCP server,
keep the `[mcp]` extra in mind when reinstalling.)

### Option A — From a git repository (recommended for teams)

No need to clone manually; pipx clones internally:

```
pipx install git+https://bitbucket.org/your-org/grove.git
```

With a specific branch or tag:

```
pipx install "git+https://bitbucket.org/your-org/grove.git@v0.1.0"
```

Advantage: a single command, cross-platform, and updatable with `pipx upgrade grove`.

### Option B — From a wheel file (no git) — **guide for whoever receives the `.whl`**

This is the path when someone **handed you the file** `grove-0.1.0-py3-none-any.whl` (via Slack, email, drive...). You don't need git or the source code: just that file. The wheel is universal (`py3-none-any`), so the same file works on Windows, macOS, and Linux.

**Step 1 — Requirements.** Have Python 3.11+ and, recommended, pipx (see §1). Verify:

```
python3 --version      # 3.11 or higher   (Windows: py --version)
pipx --version
```

**Step 2 — Save the `.whl`** in a folder you'll remember, for example `~/Downloads`.

**Step 3 — Install pointing to the file path:**

```
pipx install ~/Downloads/grove-0.1.0-py3-none-any.whl
```

On Windows (PowerShell):

```
pipx install $HOME\Downloads\grove-0.1.0-py3-none-any.whl
```

If your default Python is older than 3.11:

```
pipx install --python python3.12 ~/Downloads/grove-0.1.0-py3-none-any.whl
```

**Step 4 — Verify:**

```
gwt --version          # -> grove (gwt) 0.1.0
```

If it says "command not found", run `pipx ensurepath` and reopen the terminal (see §8).

**Alternative without pipx** (not recommended, but valid): `python3 -m pip install --user ~/Downloads/grove-0.1.0-py3-none-any.whl`. The `gwt` command will end up in the user's scripts directory; you may need to add it to the PATH.

**To update to a new wheel** handed to you later:

```
pipx install --force ~/Downloads/grove-0.1.0-py3-none-any.whl
```

### Option C — From a local folder

If you have the code on disk (folder or unzipped archive):

```
pipx install /path/to/grove/python
```

### Option D — Development mode (to modify grove)

Only if you're going to edit the code. Editable install in a virtual environment:

```
cd /path/to/grove/python
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

### Without installing (direct execution)

For a quick test without installing anything, from the project folder:

```
PYTHONPATH=src python3 -m grove --help        # macOS/Linux
```
```
set PYTHONPATH=src && py -m grove --help       # Windows (cmd)
```

---

## 3. Choosing the right Python

pipx uses your default Python. If that one is older than 3.11, tell it which to use:

```
pipx install --python python3.12 git+<repo-URL>
```

On Windows you can point to the launcher: `--python py` or to the executable's path.

---

## 4. Building the wheel (to distribute by file)

On the machine that packages it (any OS, just once):

```
cd /path/to/grove/python
python3 -m pip install build      # packaging tool, just once
python3 -m build                  # generates dist/grove-<version>-py3-none-any.whl
```

The resulting `.whl` is portable; share it and have each dev use Option B.

---

## 5. Verify the installation

```
gwt --version          # -> grove (gwt) 0.1.1
gwt --help             # list of commands
```

---

## 6. Updating

The update method depends on how it was installed. In all cases, **verify at the end** with `gwt --version` that the number went up. If you use the MCP server, **restart your MCP client** (e.g. Claude Desktop) after updating so it picks up the new `grove-mcp`.

### 6.0 If you installed it from PyPI (Option A0)

```
pipx upgrade grove-wt
```

That's it — pipx pulls the latest published version. (If you installed the MCP
server, the `grove-mcp` command stays at the same path.)

### 6.1 If you installed it from git (Option A)

```
pipx upgrade grove-wt
```

pipx re-clones the repo and reinstalls if there are changes. To force it (e.g. same branch, new commits) or to pin a released tag:

```
pipx install --force "git+https://github.com/N3Y70R/grove.git@python/v0.5.0#subdirectory=python"
```

### 6.2 If you were handed a new wheel (Option B)

When you receive a more recent version `.whl`, reinstall with `--force` pointing to the new file:

```
pipx install --force ~/Downloads/grove-0.1.1-py3-none-any.whl
```

`--force` is required: without it, pipx won't replace an existing installation. It works even if the version number doesn't change.

### 6.3 If you installed it from a local folder (Option C)

```
pipx install --force /path/to/grove/python
```

### 6.4 If it's a development install (Option D, `pip install -e`)

No reinstall needed: just update the code (`git pull`) in the folder; changes are reflected instantly because it's editable.

### 6.5 About versions

The version number lives in `pyproject.toml` (`version = "..."`) and is reflected in `gwt --version`. It's a good idea to **bump it in every wheel you distribute** (e.g. `0.1.1` → `0.1.2`) so it's easy to know which version everyone has. After changing it, rebuild the wheel (§4).

> Note: even if two wheels have the same number, `pipx install --force` always installs the contents of the file you pass it; the number is only there to orient humans.

---

## 7. Uninstall

```
pipx uninstall grove
```

---

## 8. Troubleshooting

**`gwt: command not found` right after installing**
The pipx directory isn't on the PATH yet. Run `pipx ensurepath` and reopen the terminal. On macOS/Linux it's usually `~/.local/bin`.

**`This package requires a different Python: 3.x.y not in '>=3.11'`**
Your default Python is old. Install 3.11+ (§1.1) and use `pipx install --python python3.12 ...` (§3).

**Windows: the `.ps1` script won't run ("execution policy")**
Allow scripts for the current session before running it:
```
powershell -ExecutionPolicy Bypass -File install.ps1
```

**Windows: `python`/`pip` not recognized**
Use the `py` launcher (`py --version`, `py -m pip ...`) or reinstall Python with "Add to PATH" checked.

**`pipx: command not found`**
Install pipx (§1.2). If you installed it with `pip install --user pipx`, invoke it as `python3 -m pipx ...` until you run `ensurepath`.

**Behind a corporate proxy**
`pipx`/`pip` respect `HTTP_PROXY`/`HTTPS_PROXY`. Export them before installing if your network requires it.

---

## 9. Notes per operating system

- **macOS / Linux:** standard flow; `gwt` ends up in `~/.local/bin`.
- **Windows:** works in PowerShell, cmd, and Windows Terminal. For ANSI colors use Windows 10+ / Windows Terminal. Alternatively, Git Bash or WSL provide a Linux-like environment where grove behaves the same as on macOS/Linux.

> Note: runtime behavior on Windows is still pending formal verification (paths, colors, `git worktree`). The packaging is portable; it's advisable to run `gwt setup` and `gwt list` once on Windows before adopting it across the team.
