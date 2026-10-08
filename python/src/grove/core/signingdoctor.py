"""SSH signing diagnosis and an explicit, disposable Git signing test."""
from __future__ import annotations

from functools import partial
import base64
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from . import platform, repairs, signing
from .errors import GitError, UsageError, ValidationError
from .redaction import redact

MAX_ERROR = 16384


def safe(text):
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
                  "[private key redacted]", text, flags=re.S)
    text = re.sub(r"(?i)\b(bearer\s+|(?:token|password|secret)\s*[=:]\s*)[^\s]+", r"\1[redacted]", text)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|pypi-[A-Za-z0-9_-]+)\b", "[token redacted]", text)
    return redact(text)[:MAX_ERROR]


def sanitize(value):
    if isinstance(value, str):
        return safe(value)
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    return value


def finding(check, target, message, action, *, severity="error", fixable=False, evidence=""):
    return {"check": check, "target": str(target), "message": message, "severity": severity,
            "action": action, "fixable": fixable, "evidence": safe(evidence)}


def interpret_error(text):
    if text is None or not text.strip():
        return []
    if len(text.encode("utf-8")) > MAX_ERROR:
        raise UsageError("Signing error text exceeds 16 KiB; supply a short relevant excerpt.")
    low = text.lower()
    if "verified" in low and ("signature" in low or "signed" in low):
        return [finding("remote-signature-policy", "supplied error", "The server reports a verified-signature requirement.",
                        "Check every commit in the push and the provider's signing identity/key registration; this text does not prove which check failed.", evidence=text)]
    if "allowedsignersfile" in low or "no principal matched" in low:
        check, message, action = "verification-trust", "Local signature trust is missing or does not match.", "Review allowedSignersFile, the committer email and authorized public keys."
    elif "passphrase" in low or "incorrect passphrase" in low:
        check, message, action = "key-unlock", "The error indicates that the private key needs unlocking.", "Unlock/load the key in a terminal, then run doctor --test again."
    elif "no private key" in low or "couldn't load public key" in low or "no such file" in low:
        check, message, action = "key-material", "Signing key material could not be loaded.", "Review the effective signing key path, adjacent private key and SSH agent."
    elif "failed to sign" in low or "signing failed" in low:
        check, message, action = "signing-failed", "The signer failed; the supplied error does not establish a unique cause.", "Run signing doctor --test in the affected worktree."
    else:
        check, message, action = "unclassified-error", "The supplied error has no recognized signing diagnosis.", "Review the redacted evidence and run the local signing test."
    return [finding(check, "supplied error", message, action, evidence=text)]


def _ssh_string(data):
    if len(data) < 4:
        raise ValueError("Invalid SSH data")
    size = struct.unpack(">I", data[:4])[0]
    if size > len(data) - 4:
        raise ValueError("Invalid SSH length")
    return data[4:4 + size], data[4 + size:]


def _encrypted(path):
    """Inspect only the cipher header; never decrypt or emit private material."""
    try:
        text = path.read_text(encoding="utf-8")
        if "BEGIN OPENSSH PRIVATE KEY" in text:
            data = base64.b64decode("".join(text.splitlines()[1:-1]), validate=True)
            if not data.startswith(b"openssh-key-v1\0"):
                return None
            cipher, _ = _ssh_string(data[len(b"openssh-key-v1\0"):])
            return cipher != b"none"
        if "ENCRYPTED" in text:
            return True
        return False if "PRIVATE KEY" in text else None
    except (OSError, UnicodeError, ValueError):
        return None


def _public(value):
    return value.startswith(("key::", "ssh-"))


def _material(value, directory):
    if _public(value):
        return None, value.removeprefix("key::"), None
    path = signing.key_path(value, directory).resolve()
    if not path.is_file():
        return path, None, None
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        first = ""
    if first.startswith(("ssh-", "ecdsa-", "sk-")):
        private = Path(str(path)[:-4]) if str(path).endswith(".pub") else None
        return private if private and private.is_file() else None, first, path
    pub = Path(str(path) + ".pub")
    try:
        public = pub.read_text(encoding="utf-8").strip() if pub.is_file() else None
    except (OSError, UnicodeError):
        public = None
    return path, public, pub if public else None


def _agent_has(public, *, echo=None):
    if not public:
        return None
    # Compare public blobs; ssh-add -L is read-only and cannot prompt.
    if not shutil.which("ssh-add"):
        return None
    try:
        proc = signing.run(["ssh-add", "-L"], Path.cwd(), check=False, echo=echo)
    except GitError:
        return None
    parts = public.split()
    if len(parts) < 2:
        return False
    if proc.returncode not in (0, 1):
        return None
    return any(len(line.split()) >= 2 and line.split()[1] == parts[1] for line in proc.stdout.splitlines())


def inspect(directory, *, echo=None):
    run = partial(signing.run, echo=echo)
    records = signing.configuration(directory, echo=echo)
    cfg = signing.effective(records)
    issues, callbacks = [], []
    checks = [{"check": "configuration", "status": "passed", "message": "Git effective values and origins read."}]
    enabled = cfg.get("commit.gpgsign", "false").lower() in ("true", "yes", "on", "1", "")
    fmt = cfg.get("gpg.format", "openpgp")
    if not enabled:
        issues.append(finding("signing-disabled", directory, "Automatic commit signing is disabled.", "Use signing enable with an explicit key/account if signing is intended.", severity="warning"))
    for origin in {r["origin"] for r in records if r["origin"].startswith("file:")}:
        path = signing._origin_path(origin, directory)
        try:
            signing.owned_body(signing.blockedit.read_text(path))
        except ValidationError as exc:
            issues.append(finding("managed-signing-conflict", path, str(exc), "Review the managed block; no automatic overwrite is allowed."))
    if fmt != "ssh":
        checks.append({"check": "ssh-signing", "status": "not_applicable", "message": "Effective format is " + fmt + "; no conversion attempted."})
        return records, issues, checks, callbacks
    version = run(["git", "--version"], directory).stdout
    match = re.search(r"(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (2, 34):
        issues.append(finding("git-version", directory, "Git SSH signing requires Git 2.34 or newer.", "Upgrade Git before signing."))
    ident = run(["git", "var", "GIT_COMMITTER_IDENT"], directory, check=False, echo=echo)
    if ident.returncode:
        issues.append(finding("identity-missing", directory, "Git cannot resolve the committer identity.", "Configure a name/email explicitly before creating commits."))
    program = cfg.get("gpg.ssh.program", "ssh-keygen")
    if not shutil.which(program) and not signing.key_path(program, directory).is_file():
        issues.append(finding("signer-missing", program, "The effective SSH signing program is unavailable.", "Install OpenSSH or correct gpg.ssh.program."))
    elif program == "ssh-keygen":
        capabilities = run(["ssh-keygen", "-Y", "help"], directory, check=False)
        usage = capabilities.stdout + capabilities.stderr
        if "-Y sign" not in usage or "-Y verify" not in usage:
            issues.append(finding("ssh-signing-unsupported", program, "OpenSSH does not advertise SSH signing and verification support.", "Upgrade OpenSSH or configure a compatible signing program."))
        else:
            checks.append({"check": "signer-capabilities", "status": "passed", "message": "OpenSSH advertises signing and verification."})
    else:
        checks.append({"check": "signer-capabilities", "status": "skipped", "message": "Custom signer availability checked; only --test executes it."})
    key = cfg.get("user.signingkey", "")
    if not key:
        if cfg.get("gpg.ssh.defaultkeycommand"):
            checks.append({"check": "dynamic-key", "status": "skipped", "message": "Dynamic selection is not executed during passive diagnosis; --test executes it."})
        else:
            issues.append(finding("key-missing", directory, "No SSH signing key or dynamic key command is configured.", "Enable signing with an explicit key/account."))
    else:
        private, public, pubfile = _material(key, directory)
        loaded = _agent_has(public, echo=echo)
        if private and not private.is_file():
            issues.append(finding("key-missing", private, "The signing key path does not exist.", "Correct the path explicitly; do not generate a replacement automatically."))
        elif private:
            encrypted = _encrypted(private)
            permissions = platform.check_key_perms(private)
            if encrypted is not None and permissions is False:
                callbacks.append(("key-permissions", str(private), lambda: platform.enforce_key_perms(private)))
                issues.append(finding("key-permissions", private, "The private key is accessible to other users and may be rejected by OpenSSH.", "Restrict private-key permissions; --fix applies chmod 600 on POSIX.", fixable=True))
            if encrypted and loaded is not True:
                callback = lambda: platform.agent_add(private)
                callbacks.append(("key-unlock", str(private), callback))
                issues.append(finding("key-unlock", private, "The private key is encrypted and is not known to be loaded.", "Unlock/load it in a terminal; --fix can only attempt a non-interactive agent load.", fixable=True))
            elif encrypted is None:
                issues.append(finding("key-format", private, "The private key format could not be identified.", "Check the key with OpenSSH or run the explicit signing test."))
            else:
                checks.append({"check": "key-material", "status": "passed", "message": "Private material is available; agent presence alone is not required."})
        elif public and loaded is not True:
            issues.append(finding("agent-key-missing", pubfile or "inline public key", "Only a public key is available and its private key is not known to be in the agent.", "Load the matching private key in the SSH agent, then test signing."))
        elif public and loaded is True:
            checks.append({"check": "key-material", "status": "passed", "message": "The selected public key is available through the agent."})
        else:
            issues.append(finding("key-format", key, "No usable SSH signing material could be identified.", "Check the key with OpenSSH or run the explicit signing test."))
    trust = cfg.get("gpg.ssh.allowedsignersfile")
    if not trust:
        issues.append(finding("verification-trust", directory, "No local allowedSignersFile is configured; signing can still work.", "Configure local verification trust explicitly if required.", severity="warning"))
    elif not signing.key_path(trust, directory).is_file():
        issues.append(finding("verification-trust", trust, "The configured allowedSignersFile is missing.", "Restore or correct the trust file; do not replace historical keys automatically.", severity="warning"))
    revoke = cfg.get("gpg.ssh.revocationfile")
    if revoke and not signing.key_path(revoke, directory).is_file():
        issues.append(finding("revocation-file", revoke, "The configured revocation file is missing.", "Restore or correct the revocation file before verification."))
    return records, issues, checks, callbacks


def _isolated_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "SSH_ASKPASS_REQUIRE": "never", "GIT_TERMINAL_PROMPT": "0"})
    return env


def _test_run(args, directory, env, input=None, *, echo=None):
    signing.command_echo(args, echo)
    # Detach from any controlling terminal: encrypted keys must not prompt in MCP.
    proc = subprocess.Popen(args, cwd=directory, env=env,
                            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name != "nt")
    try:
        out, err = proc.communicate(input.encode("utf-8") if input is not None else None, timeout=20)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        out, err = proc.communicate()
        return 124, out.decode("utf-8", errors="replace"), "Signing test timed out; unlock/load the selected key and retry."
    return proc.returncode, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


def _key_command(command):
    """Git split_cmdline semantics: quoting/escapes, without shell expansion.

    In double quotes Git unescapes every backslash (unlike shlex). This matters
    for Windows paths and prevents accidentally executing shell substitutions.
    """
    args, current, quote, started = [], [], None, False
    i = 0
    while i < len(command):
        char = command[i]
        if char == "\\" and quote != "'":
            i += 1
            if i == len(command):
                raise UsageError("Dynamic signing command ends with an incomplete escape.")
            current.append(command[i])
            started = True
        elif char in ("'", '\"') and quote is None:
            quote = char
            started = True
        elif char == quote:
            quote = None
        elif char.isspace() and quote is None:
            if started:
                args.append("".join(current))
                current, started = [], False
        else:
            current.append(char)
            started = True
        i += 1
    if quote:
        raise UsageError("Dynamic signing command has an unclosed quote.")
    if started:
        args.append("".join(current))
    if not args or not args[0]:
        raise UsageError("Dynamic signing command has no executable.")
    return args


def _identity(directory, cfg, *, echo=None):
    proc = signing.run(["git", "var", "GIT_COMMITTER_IDENT"], directory, check=False, echo=echo)
    match = re.match(r"(.*) <([^<>]+)> ", proc.stdout)
    if match:
        return match.group(1), match.group(2)
    return cfg.get("user.name") or "Grove signing test", cfg.get("user.email") or "grove-test@localhost"


def signing_test(directory, cfg, *, echo=None):
    run = partial(signing.run, echo=echo)
    test_run = partial(_test_run, echo=echo)
    if cfg.get("gpg.format", "openpgp") != "ssh":
        return {"status": "unsupported", "message": "The effective format is not SSH.", "cryptographic_verification": "not_run", "local_verification": "not_run"}
    env = _isolated_env()
    with tempfile.TemporaryDirectory(prefix="grove-signing-test-") as folder:
        root = Path(folder)
        run(["git", "init", "-q", str(root)], root, env=env)
        for k, v in cfg.items():
            if k not in signing.KEYS:
                continue
            if k in ("gpg.ssh.allowedsignersfile", "gpg.ssh.revocationfile") or (k == "user.signingkey" and not _public(v)):
                v = str(signing.key_path(v, directory).resolve())
            if k == "gpg.ssh.program" and ("/" in v or "\\" in v):
                v = str(signing.key_path(v, directory).resolve())
            run(["git", "config", k, v], root, env=env)
        # No hooks or existing objects/refs; commit-tree writes only into this disposable repo.
        name, email = _identity(directory, cfg, echo=echo)
        for k, v in (("user.name", name), ("user.email", email)):
            run(["git", "config", k, v], root, env=env)
        rc, tree, err = test_run(["git", "mktree"], root, env, "")
        if rc:
            return {"status": "failed", "message": safe(err), "cryptographic_verification": "not_run", "local_verification": "not_run"}
        command = cfg.get("gpg.ssh.defaultkeycommand")
        if command and not cfg.get("user.signingkey"):
            command_env = os.environ.copy()
            command_env.update(SSH_ASKPASS_REQUIRE="never", GIT_TERMINAL_PROMPT="0")
            try:
                argv = _key_command(command)
            except UsageError as exc:
                return {"status": "failed", "message": str(exc), "cryptographic_verification": "not_run", "local_verification": "not_run"}
            rc, output, err = test_run(argv, directory, command_env)
            selected = output.splitlines()[0] if output else ""
            if rc or not _public(selected):
                return {"status": "failed", "message": safe(err or "Dynamic selection did not return an SSH public key as required by Git."),
                        "cryptographic_verification": "not_run", "local_verification": "not_run"}
            run(["git", "config", "user.signingkey", selected], root, env=env)
        rc, commit, err = test_run(["git", "commit-tree", "-S", tree.strip(), "-m", "Grove temporary signing test"], root, env)
        if rc:
            low = err.lower()
            status = "needs_unlock" if any(x in low for x in ("passphrase", "sign_and_send_pubkey", "agent refused", "timed out")) else "failed"
            return {"status": status, "message": safe(err), "cryptographic_verification": "not_run", "local_verification": "not_run"}
        obj = run(["git", "cat-file", "commit", commit.strip()], root, env=env).stdout
        try:
            armor = re.search(r"-----BEGIN SSH SIGNATURE-----\n(.*?)-----END SSH SIGNATURE-----", obj, re.S).group(1)
            binary = base64.b64decode("".join(armor.split()), validate=True)
            if not binary.startswith(b"SSHSIG"):
                raise ValueError("Not an SSH signature")
            blob, _ = _ssh_string(binary[10:])  # magic + uint32 version
            kind, _ = _ssh_string(blob)
            public = kind.decode("ascii") + " " + base64.b64encode(blob).decode("ascii")
        except (AttributeError, ValueError, UnicodeError):
            return {"status": "failed", "message": "The signer did not produce a supported SSH signature.", "cryptographic_verification": "failed", "local_verification": "not_run"}
        trust = root / "allowed-signers"
        trust.write_text("* " + public + "\n", encoding="utf-8", newline="\n")
        rc, _, err = test_run(["git", "-c", "gpg.ssh.allowedSignersFile=" + str(trust),
                               "-c", "gpg.ssh.revocationFile=", "verify-commit", commit.strip()], root, env)
        local = "not_configured"
        local_evidence = ""
        if cfg.get("gpg.ssh.allowedsignersfile"):
            lrc, _, local_evidence = test_run(["git", "verify-commit", commit.strip()], root, env)
            local = "passed" if lrc == 0 else "failed"
            if local == "passed":
                signature = root / "signature"
                signature.write_text("-----BEGIN SSH SIGNATURE-----\n" + "\n".join(armor.split()) + "\n-----END SSH SIGNATURE-----\n", encoding="utf-8", newline="\n")
                payload = []
                in_signature = False
                for line in obj.splitlines(keepends=True):
                    if line.startswith("gpgsig "):
                        in_signature = True
                        continue
                    if in_signature and line.startswith(" "):
                        continue
                    in_signature = False
                    payload.append(line)
                signer = cfg.get("gpg.ssh.program", "ssh-keygen")
                if "/" in signer or "\\" in signer:
                    signer = str(signing.key_path(signer, directory).resolve())
                args = [signer, "-Y", "verify", "-n", "git", "-I", email,
                        "-f", str(signing.key_path(cfg["gpg.ssh.allowedsignersfile"], directory).resolve()), "-s", str(signature)]
                if cfg.get("gpg.ssh.revocationfile"):
                    args.extend(["-r", str(signing.key_path(cfg["gpg.ssh.revocationfile"], directory).resolve())])
                prc, pout, perr = test_run(args, root, env, "".join(payload))
                if prc:
                    local = "failed"
                local_evidence = pout + perr
        return {"status": "passed" if rc == 0 else "failed", "message": safe(err),
                "cryptographic_verification": "passed" if rc == 0 else "failed",
                "local_verification": local, "local_evidence": safe(local_evidence)}


@signing.operation_errors
def diagnose(*, cwd=None, test=False, error_text=None, fix=False, dry_run=False, echo=None):
    directory, repo = signing.context(cwd, echo=echo)
    records, initial, checks, callbacks = inspect(directory, echo=echo)
    supplied = interpret_error(error_text)
    repairs_result = {"proposed": len(callbacks), "attempted": 0, "applied": 0, "failures": []}
    remaining = initial
    if fix and not dry_run and callbacks:
        result = repairs.execute(callbacks)
        records, remaining, checks, _ = inspect(directory, echo=echo)
        resolved = {(f["check"], f["target"]) for f in initial} - {(f["check"], f["target"]) for f in remaining}
        repairs_result.update(attempted=result["attempted"], applied=sum(x in resolved for x in result["completed"]), failures=result["failures"])
    trial = {"status": "skipped" if test and dry_run else "not_run", "message": "Dry-run never signs." if test and dry_run else "Use --test for a disposable signing and verification test.",
             "cryptographic_verification": "not_run", "local_verification": "not_run"}
    if test and not dry_run:
        try:
            trial = signing_test(directory, signing.effective(records), echo=echo)
        except OSError:
            trial = {"status": "failed", "message": "The signing program could not be started.", "cryptographic_verification": "not_run", "local_verification": "not_run"}
        if trial["status"] == "passed":
            # Direct execution resolves passive uncertainty for the selected mechanism.
            remaining = [f for f in remaining if f["check"] not in
                         ("key-unlock", "agent-key-missing", "key-format", "key-missing", "signer-missing")]
        if trial["status"] in ("failed", "needs_unlock"):
            remaining = [*remaining, finding("signing-test", directory, "The controlled signing test failed.", "Review the test evidence and unlock/load the key if necessary.", evidence=trial["message"])]
        if trial.get("local_verification") == "failed":
            remaining = [*remaining, finding("verification-test", directory, "Signing succeeded but configured local verification failed.", "Review trusted principals, public keys and revocations.", evidence=trial.get("local_evidence", ""))]
    all_remaining = [*remaining, *supplied]
    return sanitize({"context": {"directory": str(directory), "repo": str(repo.root)},
                     "configuration": records, "checks": checks, "findings": [*initial, *supplied],
                     "test": trial, "repairs": repairs_result, "remaining_findings": all_remaining,
                     "dry_run": dry_run, "provider_verification": "not_checked",
                     "ok": not any(f["severity"] == "error" for f in all_remaining)})
