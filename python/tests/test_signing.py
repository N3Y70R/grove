"""Signing contracts verified with isolated repositories, keys and agents."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from grove.core import blockedit, gitidentity, platform, signing, signingdoctor, sshprov
from grove.core.errors import UsageError, ValidationError
from grove.cli.main import main
from grove.mcp import _ops


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def key(tmp_path):
    if not shutil.which("ssh-keygen"):
        pytest.skip("OpenSSH unavailable")
    path = tmp_path / "signing key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True, capture_output=True)
    return path


def enable(ctx, key, **kwargs):
    return signing.configure(enable=True, key=str(key), scope="repo", cwd=str(ctx.root / "main"), **kwargs)


def test_enable_disable_preserve_inherited_and_idempotent(repo, key):
    _, ctx = repo
    cwd = ctx.root / "main"
    git(cwd, "config", "user.name", "Original identity")
    git(cwd, "config", "commit.gpgsign", "true")
    git(cwd, "config", "gpg.format", "openpgp")
    original = (ctx.bare / "config").read_text()
    result = enable(ctx, key)
    assert result["enabled"] and result["managed"] and result["changed"]
    assert not enable(ctx, key)["changed"]
    result = signing.configure(enable=False, scope="repo", cwd=str(cwd))
    assert result["enabled"] and not result["managed"]
    assert result["effective"]["gpg.format"] == "openpgp"
    assert (ctx.bare / "config").read_text() == original
    assert not signing.configure(enable=False, scope="repo", cwd=str(cwd))["changed"]


def test_dry_run_no_target_or_backup_changes(repo, key, monkeypatch):
    _, ctx = repo
    original = (ctx.bare / "config").read_bytes()
    monkeypatch.setattr(blockedit, "write_atomic", lambda *a, **kw: pytest.fail("write during preview"))
    monkeypatch.setattr(blockedit, "backup_once", lambda *a, **kw: pytest.fail("backup during preview"))
    result = enable(ctx, key, dry_run=True)
    assert result["changed"] and result["enabled"]
    assert (ctx.bare / "config").read_bytes() == original
    assert not (ctx.bare / ".config.grove-lock").exists()


def test_conflict_edited_block(repo, key):
    _, ctx = repo
    enable(ctx, key)
    file = ctx.bare / "config"
    file.write_text(file.read_text().replace("gpgSign = true", "gpgSign = false"))
    original = file.read_bytes()
    with pytest.raises(ValidationError, match="edited"):
        signing.configure(enable=False, scope="repo", cwd=str(ctx.root / "main"))
    with pytest.raises(ValidationError, match="edited"):
        enable(ctx, key)
    assert file.read_bytes() == original


def test_worktree_override_prevents_misleading_enable(repo, key):
    _, ctx = repo
    cwd = ctx.root / "main"
    git(cwd, "config", "extensions.worktreeConfig", "true")
    git(cwd, "config", "--worktree", "commit.gpgsign", "false")
    original = (ctx.bare / "config").read_bytes()
    with pytest.raises(ValidationError, match="overridden"):
        enable(ctx, key)
    assert (ctx.bare / "config").read_bytes() == original


def test_relative_include_preserved(repo, key):
    _, ctx = repo
    other = ctx.bare / "other-config"
    other.write_text("[custom]\n\tvalue = preserved\n")
    cwd = ctx.root / "main"
    git(cwd, "config", "include.path", "other-config")
    enable(ctx, key)
    assert git(cwd, "config", "custom.value") == "preserved"
    assert git(cwd, "config", "--local", "include.path") == "other-config"


def test_public_with_adjacent_private_real_signature(repo, key):
    _, ctx = repo
    enable(ctx, Path(str(key) + ".pub"))
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), test=True)
    assert result["test"]["status"] == "passed", result
    assert result["test"]["cryptographic_verification"] == "passed"
    assert result["test"]["local_verification"] == "not_configured"
    assert not any(f["check"] == "agent-key-missing" for f in result["findings"])
    assert result["provider_verification"] == "not_checked"


def test_test_does_not_change_target_objects_refs_hooks(repo, key):
    _, ctx = repo
    cwd = ctx.root / "main"
    enable(ctx, key)
    refs = git(cwd, "show-ref")
    objects = set((ctx.bare / "objects").rglob("*"))
    hook = ctx.bare / "hooks" / "commit-msg"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 99\n")
    hook.chmod(0o755)
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert result["test"]["status"] == "passed", result
    assert git(cwd, "show-ref") == refs
    assert set((ctx.bare / "objects").rglob("*")) == objects


def test_test_configured_trust_and_wrong_principal(repo, key, tmp_path):
    _, ctx = repo
    cwd = ctx.root / "main"
    git(cwd, "config", "user.email", "test@example.com")
    enable(ctx, key)
    trust = tmp_path / "trust"
    trust.write_text("test@example.com " + Path(str(key) + ".pub").read_text())
    git(cwd, "config", "gpg.ssh.allowedSignersFile", str(trust))
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert result["test"]["local_verification"] == "passed", result
    trust.write_text("wrong@example.com " + Path(str(key) + ".pub").read_text())
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert result["test"]["cryptographic_verification"] == "passed"
    assert result["test"]["local_verification"] == "failed"
    assert not result["ok"]


def test_encrypted_key_noninteractive(repo, key, tmp_path):
    _, ctx = repo
    encrypted = tmp_path / "encrypted"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "temporary-test-passphrase", "-f", str(encrypted)], check=True)
    before = encrypted.read_bytes()
    enable(ctx, encrypted)
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), test=True)
    assert any(f["check"] == "key-unlock" for f in result["findings"])
    assert result["test"]["status"] in ("needs_unlock", "failed")
    assert encrypted.read_bytes() == before


def test_doctor_dry_run_skips_test_and_fixes(repo, key, monkeypatch):
    _, ctx = repo
    enable(ctx, key)
    monkeypatch.setattr(signingdoctor, "_encrypted", lambda *a: True)
    monkeypatch.setattr(signingdoctor, "signing_test", lambda *a, **kw: pytest.fail("signed during dry-run"))
    monkeypatch.setattr(platform, "agent_add", lambda *a: pytest.fail("loaded agent during dry-run"))
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), test=True, fix=True, dry_run=True)
    assert result["test"]["status"] == "skipped"
    assert result["repairs"]["proposed"] > 0
    assert result["repairs"]["attempted"] == 0


def test_passive_dynamic_command_not_executed(repo, tmp_path):
    _, ctx = repo
    cwd = ctx.root / "main"
    sentinel = tmp_path / "must-not-exist"
    git(cwd, "config", "gpg.format", "ssh")
    git(cwd, "config", "gpg.ssh.defaultKeyCommand", "touch " + str(sentinel))
    signingdoctor.diagnose(cwd=str(cwd))
    assert not sentinel.exists()


def test_error_interpretation_redacts_and_bounds():
    error = "remote requires verified signatures https://user:pass@example.com token=secretvalue\n-----BEGIN OPENSSH PRIVATE KEY-----\nprivate-material\n-----END OPENSSH PRIVATE KEY-----"
    result = signingdoctor.interpret_error(error)
    assert result[0]["check"] == "remote-signature-policy"
    assert "secretvalue" not in result[0]["evidence"]
    assert "private-material" not in result[0]["evidence"]
    assert "user:pass" not in result[0]["evidence"]
    with pytest.raises(UsageError):
        signingdoctor.interpret_error("x" * 17000)
    assert signingdoctor.interpret_error("unexpected unrelated failure")[0]["check"] == "unclassified-error"


def test_json_cli_mcp_parity_and_cwd(repo, key, capsys, monkeypatch, tmp_path):
    _, ctx = repo
    cwd = str(ctx.root / "main")
    monkeypatch.chdir(tmp_path)
    assert main(["signing", "enable", "--scope", "repo", "--key", str(key), "-C", cwd, "--json", "-v", "--dry-run"]) == 0
    cli = json.loads(capsys.readouterr().out)["result"]
    assert cli == _ops.op_signing_enable(scope="repo", key=str(key), cwd=cwd, dry_run=True)
    main(["signing", "doctor", "-C", cwd, "--json", "-v", "--test", "--fix", "--dry-run"])
    cli = json.loads(capsys.readouterr().out)["result"]
    assert cli == _ops.op_signing_doctor(cwd=cwd, test=True, fix=True, dry_run=True)


def test_zone_signing_survives_account_routing_lifecycle(repo, key):
    _, ctx = repo
    cwd = ctx.root / "main"
    folder = ctx.root.parent
    paths = platform.paths()
    gitidentity.upsert_zone(folder, "test@example.com", {"github.com": "example"}, paths)
    result = signing.configure(enable=True, key=str(key), scope="zone", scope_dir=str(folder), cwd=str(cwd))
    assert result["enabled"]
    gitidentity.upsert_zone(folder, "test@example.com", {"gitlab.com": "other"}, paths)
    assert git(cwd, "config", "user.signingkey") == str(key)
    gitidentity.remove_account_from_zone(folder, "example", paths)
    gitidentity.remove_account_from_zone(folder, "other", paths)
    assert git(cwd, "config", "user.signingkey") == str(key)
    assert Path(result["file"]).exists()
    result = signing.configure(enable=False, scope="zone", scope_dir=str(folder), cwd=str(cwd))
    assert not result["managed"]


def test_mcp_signing_schemas_keep_every_field(repo, key):
    pytest.importorskip("mcp")
    from grove.mcp import server
    _, ctx = repo
    for name, args in (("grove_signing_enable", {"scope": "repo", "key": str(key), "dry_run": True}),
                       ("grove_signing_disable", {"scope": "repo", "dry_run": True}),
                       ("grove_signing_doctor", {"test": True, "dry_run": True})):
        args["cwd"] = str(ctx.root / "main")
        result = asyncio.run(server.mcp.call_tool(name, args))
        assert not result.is_error, result
        assert result.structured_content == json.loads(result.content[0].text)


@pytest.fixture
def agent(key, monkeypatch):
    if os.name == "nt" or not shutil.which("ssh-agent"):
        pytest.skip("Isolated POSIX ssh-agent required")
    import tempfile
    import time
    with tempfile.TemporaryDirectory(prefix="grove-agent-", dir="/tmp") as folder:
        sock = Path(folder) / "agent.sock"
        proc = subprocess.Popen(["ssh-agent", "-D", "-a", str(sock)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if sock.exists():
                    break
                time.sleep(.01)
            monkeypatch.setenv("SSH_AUTH_SOCK", str(sock))
            subprocess.run(["ssh-add", str(key)], check=True, capture_output=True)
            yield sock
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def test_dynamic_selection_runs_only_in_explicit_test(repo, key, tmp_path, agent):
    _, ctx = repo
    cwd = ctx.root / "main"
    sentinel = tmp_path / "selected"
    script = tmp_path / "selector.py"
    pub = "key::" + Path(str(key) + ".pub").read_text().strip()
    script.write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text(str(Path.cwd()))\nprint(" + repr(pub) + ")\n")
    import sys
    import shlex
    command = shlex.quote(sys.executable) + " " + shlex.quote(str(script))
    git(cwd, "config", "gpg.format", "ssh")
    git(cwd, "config", "gpg.ssh.defaultKeyCommand", command)
    signingdoctor.diagnose(cwd=str(cwd), test=True, dry_run=True)
    assert not sentinel.exists()
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert Path(sentinel.read_text()).resolve() == cwd.resolve()
    assert result["test"]["status"] == "passed", result



def test_private_agent_for_inline_public_signing(repo, key, agent):
    _, ctx = repo
    cwd = ctx.root / "main"
    git(cwd, "config", "gpg.format", "ssh")
    git(cwd, "config", "user.signingkey", "key::" + Path(str(key) + ".pub").read_text().strip())
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert result["test"]["status"] == "passed", result
    assert not any(f["check"] == "agent-key-missing" for f in result["findings"])



def test_only_public_key_without_agent_is_diagnosed(repo, key, tmp_path):
    _, ctx = repo
    public = tmp_path / "public only"
    public.write_text(Path(str(key) + ".pub").read_text())
    enable(ctx, public)
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), test=True)
    assert any(f["check"] == "agent-key-missing" for f in result["findings"])
    assert result["test"]["status"] == "failed"


def test_repair_failure_and_verified_success(repo, monkeypatch):
    _, ctx = repo
    target = "test-key"
    callback = lambda: False
    issue = signingdoctor.finding("key-unlock", target, "locked", "unlock", fixable=True)
    monkeypatch.setattr(signingdoctor, "inspect", lambda d, **kw: ([], [issue], [], [("key-unlock", target, callback)]))
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), fix=True)
    assert result["repairs"]["attempted"] == 1 and result["repairs"]["applied"] == 0
    assert result["repairs"]["failures"] and result["remaining_findings"]
    seen = []
    callback = lambda: seen.append("loaded")
    monkeypatch.setattr(signingdoctor, "inspect", lambda d, **kw: ([], [] if seen else [issue], [], [("key-unlock", target, callback)]))
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), fix=True)
    assert result["repairs"]["applied"] == 1 and not result["remaining_findings"]


def test_account_selection_and_zone_ambiguity(repo, key):
    _, ctx = repo
    paths = platform.paths()
    blockedit.write_atomic(paths.ssh_config, blockedit.upsert_block("", "account", "test-gh", "Host test-gh\n    HostName github.com\n    IdentityFile " + gitidentity._quote(str(key))))
    result = signing.configure(enable=True, account="test-gh", scope="repo", cwd=str(ctx.root / "main"))
    assert result["effective"]["user.signingkey"] == str(key)
    with pytest.raises(UsageError, match="exactly one"):
        signing.configure(enable=True, account="test-gh", key=str(key), cwd=str(ctx.root / "main"))
    with pytest.raises(UsageError, match="existing"):
        signing.configure(enable=True, account="unknown", cwd=str(ctx.root / "main"))
    with pytest.raises(UsageError, match="existing"):
        signing.configure(enable=True, key=str(key), scope="zone", scope_dir=str(ctx.root.parent), cwd=str(ctx.root / "main"))


def test_file_and_environment_context_and_key_validation(repo, key, monkeypatch, tmp_path):
    _, ctx = repo
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    with pytest.raises(ValidationError, match="overridden"):
        enable(ctx, key)
    monkeypatch.delenv("GIT_CONFIG_COUNT")
    invalid = tmp_path / "invalid-key"
    invalid.write_text("This is not a key")
    with pytest.raises(ValidationError, match="not a readable"):
        enable(ctx, invalid)
    # Container works without an optional .git pointer.
    (ctx.root / ".git").unlink(missing_ok=True)
    result = signing.configure(enable=True, key=str(key), scope="repo", cwd=str(ctx.root))
    assert result["enabled"]


def test_unknown_signing_format_never_changed_by_doctor(repo):
    _, ctx = repo
    cwd = ctx.root / "main"
    git(cwd, "config", "gpg.format", "x509")
    before = (ctx.bare / "config").read_bytes()
    result = signingdoctor.diagnose(cwd=str(cwd), fix=True, test=True)
    assert result["test"]["status"] == "unsupported"
    assert (ctx.bare / "config").read_bytes() == before


def test_error_file_limits_and_secret_redaction(repo, tmp_path, capsys):
    _, ctx = repo
    file = tmp_path / "error.txt"
    file.write_text("signature signing failed token=temporarysecret pypi-exampleSecret")
    assert main(["signing", "doctor", "-C", str(ctx.root / "main"), "--error-file", str(file), "--json"]) == 1
    out = capsys.readouterr().out
    assert "temporarysecret" not in out and "exampleSecret" not in out
    file.write_text("x" * 17000)
    assert main(["signing", "doctor", "-C", str(ctx.root / "main"), "--error-file", str(file), "--json"]) == 3
    json.loads(capsys.readouterr().out)


def test_disable_plan_respects_higher_override(repo, key):
    _, ctx = repo
    cwd = ctx.root / "main"
    enable(ctx, key)
    git(cwd, "config", "extensions.worktreeConfig", "true")
    git(cwd, "config", "--worktree", "commit.gpgsign", "true")
    preview = signing.configure(enable=False, scope="repo", cwd=str(cwd), dry_run=True)
    result = signing.configure(enable=False, scope="repo", cwd=str(cwd))
    assert preview["effective"] == result["effective"]
    assert preview["enabled"] and result["enabled"]


def test_identity_environment_is_used_by_trust_test(repo, key, monkeypatch, tmp_path):
    _, ctx = repo
    cwd = ctx.root / "main"
    git(cwd, "config", "user.email", "configured@example.com")
    enable(ctx, key)
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "environment@example.com")
    trust = tmp_path / "trust"
    trust.write_text("environment@example.com " + Path(str(key) + ".pub").read_text())
    git(cwd, "config", "gpg.ssh.allowedSignersFile", str(trust))
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert result["test"]["local_verification"] == "passed", result


def test_refuses_different_git_dir(repo, key, monkeypatch, tmp_path):
    _, ctx = repo
    other = tmp_path / "other.git"
    git(tmp_path, "init", "--bare", str(other))
    monkeypatch.setenv("GIT_DIR", str(other))
    original = (ctx.bare / "config").read_bytes()
    with pytest.raises(UsageError, match="different repository"):
        enable(ctx, key)
    assert (ctx.bare / "config").read_bytes() == original


def test_private_key_permissions_preview_and_verified_repair(repo, key):
    if os.name == "nt":
        pytest.skip("POSIX key permission semantics")
    _, ctx = repo
    enable(ctx, key)
    key.chmod(0o644)
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), fix=True, dry_run=True)
    assert any(f["check"] == "key-permissions" for f in result["remaining_findings"])
    assert key.stat().st_mode & 0o777 == 0o644
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), fix=True)
    assert result["repairs"]["applied"] == 1
    assert not any(f["check"] == "key-permissions" for f in result["remaining_findings"])
    assert key.stat().st_mode & 0o777 == 0o600


def test_doctor_reports_edited_signing_block(repo, key):
    _, ctx = repo
    enable(ctx, key)
    file = ctx.bare / "config"
    file.write_text(file.read_text().replace("gpgSign = true", "gpgSign = false"))
    result = signingdoctor.diagnose(cwd=str(ctx.root / "main"), fix=True)
    assert any(f["check"] == "managed-signing-conflict" for f in result["remaining_findings"])
    assert not result["ok"]


def test_dynamic_command_invalid_output_rejected_as_git_would(repo, key, tmp_path):
    _, ctx = repo
    cwd = ctx.root / "main"
    script = tmp_path / "selector.py"
    script.write_text("print(" + repr(str(key)) + ")\n")
    import sys
    import shlex
    git(cwd, "config", "gpg.format", "ssh")
    git(cwd, "config", "gpg.ssh.defaultKeyCommand", shlex.quote(sys.executable) + " " + shlex.quote(str(script)))
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert result["test"]["status"] == "failed", result


def test_dynamic_command_quoting_matches_git_rules():
    assert signingdoctor._key_command('program "a\\ b" \'literal\\path\' ""') == ["program", "a b", "literal\\path", ""]
    assert signingdoctor._key_command('program $(touch file)') == ["program", "$(touch", "file)"]
    with pytest.raises(UsageError):
        signingdoctor._key_command('program "unfinished')


def test_dynamic_command_sees_original_repository(repo, key, agent, tmp_path):
    _, ctx = repo
    cwd = ctx.root / "main"
    git(cwd, "config", "gpg.format", "ssh")
    git(cwd, "config", "custom.selector", "source-context")
    script = tmp_path / "selector.py"
    result_file = tmp_path / "selected-context"
    pub = "key::" + Path(str(key) + ".pub").read_text().strip()
    script.write_text("import subprocess\nfrom pathlib import Path\nvalue = subprocess.check_output(['git', 'config', 'custom.selector'], text=True).strip()\nPath(" + repr(str(result_file)) + ").write_text(value)\nprint(" + repr(pub) + ")\n")
    import sys
    import shlex
    git(cwd, "config", "gpg.ssh.defaultKeyCommand", shlex.quote(sys.executable) + " " + shlex.quote(str(script)))
    result = signingdoctor.diagnose(cwd=str(cwd), test=True)
    assert result["test"]["status"] == "passed", result
    assert result_file.read_text() == "source-context"


def test_first_time_cli_account_to_signing_flow(repo, key, capsys):
    _, ctx = repo
    assert main(["ssh", "add", "first-gh", "--host", "github.com", "--key", str(key), "--no-identity", "--no-agent", "--print-pubkey"]) == 0
    public = capsys.readouterr().out.strip()
    assert public == Path(str(key) + ".pub").read_text().strip()
    cwd = str(ctx.root / "main")
    assert main(["signing", "enable", "--account", "first-gh", "--scope", "repo", "-C", cwd, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["enabled"]
    assert main(["signing", "doctor", "--test", "-C", cwd, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)["result"]
    assert result["test"]["status"] == "passed" and result["provider_verification"] == "not_checked"


def test_two_identity_zones_keep_personal_and_work_signing_separate(repo, origin, key, tmp_path, monkeypatch):
    _, personal = repo
    # All repos and keys are disposable; mirrors two independently configured roots.
    work_root = tmp_path / "work-company" / "github" / "workspace"
    created = _ops.op_setup(url=origin, into=str(work_root), name="work-repo", base="main")
    work = Path(created["root"])
    work_key = tmp_path / "work-signing-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(work_key)], check=True, capture_output=True)
    paths = platform.paths()
    personal_zone = personal.root.parent
    work_zone = work_root.parent
    gitidentity.upsert_zone(personal_zone, "personal@example.com", {"github.com": "personal-gh"}, paths)
    gitidentity.upsert_zone(work_zone, "work@example.com", {"github.com": "work-gh"}, paths)
    for alias, folder, selected in (("personal-gh", personal_zone, key), ("work-gh", work_zone, work_key)):
        text = blockedit.read_text(paths.ssh_config)
        body = "Host " + alias + "\n    HostName github.com\n    IdentityFile " + gitidentity._quote(str(selected)) + "\n    # grove-zone: " + platform.normalize_gitdir(folder)
        blockedit.write_atomic(paths.ssh_config, blockedit.upsert_block(text, "account", alias, body))
    pcwd, wcwd = personal.root / "main", work / "main"
    signing.configure(enable=True, account="personal-gh", scope="zone", cwd=str(pcwd))
    signing.configure(enable=True, account="work-gh", scope="zone", cwd=str(wcwd))
    assert git(pcwd, "config", "user.signingkey") == str(key)
    assert git(wcwd, "config", "user.signingkey") == str(work_key)
    assert git(pcwd, "config", "user.email") == "personal@example.com"
    assert git(wcwd, "config", "user.email") == "work@example.com"
    with pytest.raises(UsageError, match="inside"):
        signing.configure(enable=True, account="work-gh", scope="zone", cwd=str(pcwd))
    signing.configure(enable=False, scope="zone", scope_dir=str(personal_zone), cwd=str(pcwd))
    assert git(wcwd, "config", "user.signingkey") == str(work_key)
    # Repo context rather than process cwd controls both doctor calls.
    monkeypatch.chdir(tmp_path)
    result = signingdoctor.diagnose(cwd=str(wcwd), test=True)
    assert result["test"]["status"] == "passed", result


def test_human_cli_output_and_plan(repo, key, capsys):
    _, ctx = repo
    cwd = str(ctx.root / "main")
    assert main(["signing", "enable", "--key", str(key), "--scope", "repo", "-C", cwd, "--dry-run", "--no-color"]) == 0
    assert "Signing plan prepared" in capsys.readouterr().out
    assert main(["signing", "doctor", "-C", cwd, "--no-color"]) == 0
    assert "Test: not_run" in capsys.readouterr().out
