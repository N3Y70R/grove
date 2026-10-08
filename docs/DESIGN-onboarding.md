# Onboarding aggregation

The first-use flow has separate boundaries: installed CLI, skill files, client
skill loading, and MCP connection. `onboard` reports these independently and
cannot certify the latter two from terminal. The specification defines its
result/arguments and offline defaults (§16).

Core delegates skill inventory/install, SSH doctor and signing doctor to existing
operations. CLI and MCP remain thin facades with the same result. Dependencies
are tested using the executing Python environment; detecting another globally
installed executable is insufficient. Skill inspection uses its existing status
and dry-run installation plan to catch incomplete files and edited copies.

No account selection, client configuration edits or force installation. Optional
diagnostics do not change the user's personal/work identity zones. Client names
choose instructions only, not proof of availability; unsupported names are data.
PyPI checks are optional, bounded and skipped during dry-run. Client verification
instructions use the actual runtime version rather than a hardcoded release.
