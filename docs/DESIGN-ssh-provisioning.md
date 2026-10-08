# Implementation design — SSH account provisioning

Companion to spec §14. Implemented by the Python core, CLI and MCP facades.

## Layers and boundaries

- `platform.py`: home/config paths, OS permissions, agent/keychain operations.
- `blockedit.py`: validated marked regions, backups and atomic writes.
- `gitidentity.py`: Git global scalars, conditional includes and zone identities.
- `sshprov.py`: derived account/zone inventory and provisioning orchestration.
- `sshdoctor.py`: findings, repair callbacks and verified reports.
- `repairs.py`: callback ordering supplied by each doctor, deduplication and failures.
- `sshcheck.py`: OpenSSH configuration resolution and optional live authentication.
- `cli/commands/ssh.py`: argument handling, interaction and presentation.
- `mcp/_ops.py`, `server.py`, `schemas.py`: local operations and typed tool contracts.

Provisioning uses local OpenSSH/Git processes and does not upload public keys.
Git remote operations and explicit live authentication checks can access the network.
Identity email selects the commit author; it does not cryptographically sign commits.
There are no signing commands or provider API clients in this correction.

## Context and inventory

Resolve home and SSH paths per call. `GIT_CONFIG_GLOBAL`, when set, selects the
Git file that Grove manages as well as the one used by `git config --global`.
Relative identity includes resolve from that global file's directory.
`ssh -G -F <config>` resolves the selected SSH configuration, including manual
rules, instead of silently using OpenSSH's passwd-based home.

Inventory is derived from canonical files; there is no separate registry.
Validate all Grove markers before interpreting or editing them. Duplicate,
unbalanced and nested regions fail without regenerating configuration.

## Zones and preservation

New zone IDs combine a readable folder slug with the first 12 hexadecimal
digits of SHA-256 over the normalized absolute scope. Paths use forward slashes,
a trailing slash, lexical normalization and no symlink resolution or case folding.
Relative scopes remain relative to home, matching the existing convention.

Existing zones retain their IDs and actual included files. Reads and mutations
resolve the marked include rather than reconstructing filenames from folder names.
Reject duplicate scopes, shared identity files, occupied unreferenced destination
files and conflicting email/host routing before key generation or configuration edits.
Do not infer emails that were never stored or recover overwritten data by guessing.

Git parses and edits a temporary copy of an identity file (`git config --file`,
without loading includes). Grove owns its author email and canonical host rewrites;
Git preserves other options, repeated settings, includes and comments. Only exact
canonical rewrite values belonging to the managed alias are removed.

Removing the last account also removes the managed email. Retain the identity
and include if any other setting or user comment remains. Delete only an empty
zone. Upsert, removal and doctor repair use the same identity layer.

## Writes, conflicts and failures

Each operation has a backup scope. Snapshot each existing file once per operation,
using a timestamp, path digest and unique suffix. Backups and replacement files
use private temporary files. Replacement is atomic on the same filesystem. Preserve existing configuration
symlinks by replacing their resolved target, and reject shared zone targets.

In-process edit scopes serialize edits. A stable `.grove-lock` sidecar coordinates
writers per file; compare the originally read text before replacing it, and reject
an intervening change. Keep the lock file to retain a stable inode. No lock,
backup or replacement is created by a dry-run.

Operations affecting several files are not transactions. A later failure may leave
earlier steps applied; propagate the failure and use `ssh accounts` / `ssh doctor`
to inspect the state before retrying. Do not silently swallow key deletion failures.

## Diagnosis and repair

Both doctors use the shared callback executor and diagnose again after repairs.
Keep initial findings, distinct attempted callbacks, failures and remaining findings.
`applied` counts callback outcomes whose original diagnosis no longer remains;
a callback returning `False` or raising an operational error is not success.
Deduplicate shared callbacks and retain the repository doctor's existing fix order.

SSH checks include missing identity files, absent keys, permissions, missing or
false `IdentitiesOnly`, missing routing, author defaults, embedded URL credentials,
and effective SSH settings that disagree with the managed account. Manual SSH
rules are reported and never edited. An unavailable agent is an unknown load
state; an available empty agent means the key is not loaded.

CLI repository doctor keeps exit 0 for a completed diagnosis. SSH doctor exits 1
while findings or repair failures remain. MCP returns the structured report:
completion of the tool is separate from absence of findings.

## Simulation and interaction

`fix` never overrides `dry_run`. Skip callbacks as well as mutating Git commands,
key generation, key deletion, backups and agent loading. A simulated new worktree
has no path/upstream to verify yet. Read commands disable optional Git locks.

JSON emits one object; verbose traces belong in its `log`. JSON with
`--confirm-each` is a usage error. JSON and MCP never prompt. Reuse encrypted
keys as-is; generating one requires an interactive CLI terminal unless the caller
explicitly chooses no passphrase. Noninteractive agent operations disable askpass,
detach from the terminal and time out. Report unsuccessful agent loading explicitly.

CLI/MCP operation scopes serialize the mutable configuration policy, reset it to
known defaults at entry and restore it at exit, including failures. Explicit `-C`
and MCP `cwd` control implicit worktree selection.

## Verification and delivery

Tests isolate Git/SSH config and agents. Regression coverage exercises simulation,
JSON, explicit context, interleaved policy calls, legacy/colliding zones, independent
signing settings, atomic conflicts, failures, timeouts and CLI/MCP output contracts.
CI runs Python 3.11–3.14 and selected foundation tests on macOS/Windows.

Publish through language tags after merge and CI. The release workflow checks
metadata, changelog and ancestry on `main`, runs tests and skill validation, then
builds and publishes. See CONTRIBUTING for the final release commit and tagging flow.
