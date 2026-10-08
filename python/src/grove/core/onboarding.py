"""Aggregate first-use checks; never edit client configuration or identities."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.request import urlopen

from .. import __version__
from . import config, skill
from .errors import UsageError, WtError

CLIENTS = {"agents", "codex", "claude-code", "claude-desktop", "cursor"}


def _git_version():
    try:
        result = subprocess.run(["git", "--version"], capture_output=True,
                                text=True, timeout=10)
        return result.returncode == 0, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, "Git could not be executed."


def _mcp_available():
    try:
        importlib.import_module("grove.mcp.server")
        return True
    except (ImportError, OSError):
        return False


def _latest_version():
    with urlopen("https://pypi.org/pypi/grove-wt/json", timeout=5) as response:
        payload = response.read(1048577)
    if len(payload) > 1048576:
        raise ValueError("Response exceeds the readiness check limit.")
    latest = json.loads(payload)["info"]["version"]
    if not isinstance(latest, str) or not re.fullmatch(r"\d+\.\d+\.\d+", latest):
        raise ValueError("No stable version available.")
    return latest


def _instructions(client):
    # Launch the verified environment, even when its entrypoint is not on PATH.
    command = sys.executable
    quoted = "'" + command.replace("'", "''") + "'" if sys.platform == "win32" else shlex.quote(command)
    invocation = quoted + " -m grove.mcp"
    if client == "claude-code":
        return ["Register manually with Claude Code: claude mcp add --transport stdio grove -- " + invocation]
    if client in {"claude-desktop", "cursor"}:
        fragment = json.dumps({"mcpServers": {"grove": {"command": command, "args": ["-m", "grove.mcp"]}}})
        return [f"Merge this entry into {client}'s MCP configuration using its documented settings: {fragment}"]
    if client == "codex":
        return ["Register manually with Codex: codex mcp add grove -- " + invocation]
    return [f"Register an stdio MCP server in your client with executable {command} and arguments -m grove.mcp; see docs/MCP.md."]


@config.isolated_operation
def report(*, channel="cli", client="agents", target="agents", path=None,
           install_skill=False, dry_run=False, check_update=False,
           ssh=False, signing=False, cwd=None):
    if channel not in {"cli", "mcp"} or target not in {"agents", "claude", "project"}:
        raise UsageError("Choose channel cli|mcp and target agents|claude|project.")
    checks, steps = [], []
    installation = None

    def add(name, status, message):
        checks.append({"name": name, "status": status, "message": message})

    add("grove", "passed", f"Running grove {__version__} with {sys.executable}.")
    ok, version = _git_version()
    add("git", "passed" if ok else "error", version or "Git is unavailable.")
    supported = client in CLIENTS
    add("client", "not_verified" if supported else "action_required",
        "Client installation and skill loading must be checked in the client." if supported
        else "Unknown client; use --path for its skill destination and follow its documentation.")
    if supported and client in {"codex", "claude-code"}:
        executable = "claude" if client == "claude-code" else "codex"
        detected = shutil.which(executable)
        checks[-1]["message"] += (f" Executable detected at {detected}; this does not prove integration."
                                 if detected else f" {executable} was not detected on PATH; follow the client's installation instructions.")
    try:
        if path:
            root = Path(path).expanduser()
            if not root.is_absolute():
                root = (Path(cwd) if cwd else Path.cwd()) / root
            root = root.resolve()
        else:
            root = skill.target_root(target, cwd=Path(cwd) if cwd else None)
        dest = root / skill.SKILL_NAME
        if install_skill:
            # Preview conflicts before application; never force a personalized copy.
            preview = skill.install(dest_root=root, dry_run=True)
            if dry_run or preview["mode"] in {"edited", "unverified"}:
                installation = preview
            else:
                installation = skill.install(dest_root=root)
        st = skill.status(dest)
        preview = skill.install(dest_root=root, dry_run=True)
        if preview["mode"] == "unchanged" and not st["outdated"] and st["edited"] is False:
            add("skill", "passed", f"Complete, unedited skill {st['installed_version']} at {dest}.")
        else:
            add("skill", "action_required", f"Skill at {dest}: version {st['installed_version'] or 'missing'}, integrity {preview['mode']}.")
            steps.append("Review the selected destination and run gwt skill install with the same target/path; review edits before --force.")
    except (WtError, OSError) as exc:
        add("skill", "action_required", str(exc))
    if channel == "mcp":
        ok = _mcp_available()
        add("mcp", "passed" if ok else "error", "MCP server imports in the running environment." if ok
            else 'Install grove-wt[mcp] in the environment running Grove.')
        if supported:
            steps.extend(_instructions(client))
        steps.append(f"Ask your agent to call grove_skill_status; its version must be {__version__}. Then check separately that the client loaded Grove's skill.")
    else:
        steps.append(f"Ask your terminal-capable agent to run gwt --version; expect {__version__}, and check that it loaded Grove's skill.")
    if check_update:
        if dry_run:
            add("update", "skipped", "Dry-run skips the optional network check.")
        else:
            try:
                latest = _latest_version()
                newer = tuple(map(int, latest.split('.'))) > tuple(map(int, __version__.split('.')))
                add("update", "available" if newer else "passed", f"PyPI reports {latest}; installed {__version__}. This is the index response, not a guarantee against stale data.")
            except (OSError, ValueError, KeyError, TypeError):
                add("update", "inconclusive", "Could not verify a stable version from PyPI; no update was performed.")
    for name, requested in (("ssh", ssh), ("signing", signing)):
        if not requested:
            continue
        try:
            if name == "ssh":
                from . import sshdoctor
                result = sshdoctor.report(fix=False, dry_run=dry_run, interactive=False)
                findings = result.get("remaining_findings", result.get("findings", []))
            else:
                from . import signingdoctor
                result = signingdoctor.diagnose(cwd=cwd, test=False, fix=False, dry_run=dry_run)
                findings = result.get("remaining_findings", result.get("findings", []))
            add(name, "action_required" if findings else "passed", f"Optional {name} diagnosis: {len(findings)} findings; no repairs or signing tests.")
            if findings:
                steps.append(f"Run gwt {'ssh doctor' if name == 'ssh' else 'signing doctor'} in the selected context for detailed findings.")
        except (WtError, OSError) as exc:
            add(name, "action_required", f"Optional diagnosis unavailable: {exc}")
    verdict = ("problem" if any(c["status"] == "error" for c in checks) else
               "action_required" if any(c["status"] == "action_required" for c in checks) else
               "pending_client" if channel == "mcp" else "ready_cli")
    result = {"version": __version__, "channel": channel, "verdict": verdict,
              "dry_run": dry_run, "checks": checks, "next_steps": steps}
    if installation is not None:
        result["installation"] = installation
    return result
