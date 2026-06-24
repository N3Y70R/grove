# grove — Python implementation

Reference implementation of **grove** (the `gwt` command). Standard library only; requires **Python 3.11+** (uses `tomllib`).

To learn how to use the tool, see the shared documentation in [`../docs/`](../docs/); for the design, see [`../spec/specification.md`](../spec/specification.md). This README covers only what's specific to the Python implementation.

## Installation

With [pipx](https://pipx.pypa.io/) (recommended):

```
# from the repo folder
pipx install ./python

# from git, pointing at the subdirectory
pipx install "git+https://github.com/N3Y70R/grove.git#subdirectory=python"
```

Verify with `gwt --version`. Full guide (other systems, updating, troubleshooting) in [`../docs/INSTALL.md`](../docs/INSTALL.md).

Development (editable):

```
cd python
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Building the wheel

```
cd python
python3 -m pip install --upgrade build
python3 -m build --wheel        # produces dist/grove-<version>-py3-none-any.whl
```

The wheel is universal (`py3-none-any`): it works on Windows, macOS and Linux.

## Architecture

- `src/grove/core/`: reusable logic (convention, validations, git). Designed so a future MCP facade can import it directly.
- `src/grove/cli/`: command-line facade (argparse + presentation).

## Version

The version lives in `pyproject.toml`. Releases tagged `python/vX.Y.Z`.
