# SSH commit signing

Signing extends Git identity configuration; Git remains the source of truth.
`core/signing.py` resolves context/config provenance, validates key/scope, plans
selective edits and applies them through `blockedit`. `core/signingdoctor.py`
inspects material/tools/trust, interprets supplied errors and runs disposable
signing tests. CLI and MCP adapt these operations without duplicating rules.

The signing block owns three Git settings, with a SHA-256 body checksum to reject
manual changes. Enable appends a validated block; existing external settings
remain available after removal. There is no separate state file to restore stale
values. Atomicity is per file, with expected-content comparison and backups.
An existing zone is required, avoiding a new multi-file provisioning transaction.
Signing and authentication keys can differ; account routing does not select a
signing key implicitly. Removing authentication routes retains signing settings.

A preview uses Git to parse a temporary configuration copy and resolves relative
include paths against the original file. It evaluates conditional includes in
the selected context and rejects competing/higher override sources. This is a
conservative conflict policy: a same-scope include owning signing values must be
reviewed before enabling, even if appending might override it. Reinspection after
writing detects intervening effective changes; files are not blindly restored.

An explicit test signs a temporary commit with `git commit-tree`, not a target
commit. It copies only effective signing/identity settings to a disposable repo,
resolves relevant paths from the source directory and clears Git environment
configuration overrides. The committer identity is resolved from source Git,
including identity environment overrides. Dynamic selection runs only for an
explicit test, in the source directory, with a timeout and no terminal prompts.
The configured signer is executable user configuration; test is explicit about
running it. Custom programs must support OpenSSH signing/verification semantics.

The resulting SSH signature embeds a public key. Temporary wildcard trust for
that key verifies cryptographic consistency, separately from the configured
allowedSignersFile/revocations. Configured verification also checks the effective
committer principal. This proves neither a provider's registration nor its
acceptance of other commits in a push. Missing local trust is advisory because
it is not required to create signatures.

Tests isolate home, global Git config, keys, agent and repositories. The target
repository must keep its objects/refs unchanged; no target hooks run. POSIX tests
launch their own agent/socket and terminate it. Encrypted keys stay encrypted;
failed repairs are never reported as completed solely because callbacks ran.

Dynamic selection follows Git's command-line quoting rules, without shell
expansion, and must return an inline SSH public key on the first line. It runs
with the source cwd/environment so selectors can query the real branch/config;
then the disposable test uses the selected public key. User-configured selector
and signer programs can have their own effects beyond Grove's file operations.
See [Git signing configuration](https://git-scm.com/docs/git-config#Documentation/git-config.txt-gpgsshdefaultKeyCommand).
