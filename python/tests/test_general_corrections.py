"""Regressions found while reviewing Grove's shared CLI/MCP foundation."""

import json
from pathlib import Path

import pytest

from grove.cli.main import main
from grove.cli.output import Output
from grove.core import blockedit, config, gitidentity, platform, sshdoctor
from grove.core.errors import ValidationError


@pytest.mark.parametrize("verbose", [False, True])
def test_ssh_doctor_fix_dry_run_json_never_calls_fixer(monkeypatch, capsys, verbose):
    calls = []
    finding = sshdoctor.Finding("probe", "fix", "key", "probe", lambda: calls.append(1))
    monkeypatch.setattr(sshdoctor, "diagnose", lambda **kw: [finding])
    argv = ["ssh", "doctor", "--fix", "--dry-run", "--json"]
    if verbose:
        argv.append("--verbose")
    assert main(argv) == 1
    report = json.loads(capsys.readouterr().out)["result"]
    assert calls == []
    assert report["applied"] == 0


def test_verbose_json_keeps_trace_in_log(capsys):
    out = Output(json_mode=True, verbose=True)
    out.git_echo(["git", "status"])
    assert capsys.readouterr().out == ""
    assert out.log == ["$ git status"]


def test_json_confirmation_is_usage_error_without_prompt(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("unexpected prompt"))
    assert main(["list", "--json", "--confirm-each"]) == 3
    assert json.loads(capsys.readouterr().out)["error_type"] == "UsageError"


def test_load_does_not_inherit_previous_policy(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "grove.toml").write_text(
        'relative_worktrees = true\nssh_alias = "custom"\n'
        'ticket_prefixes = ["OPS"]\n', encoding="utf-8")
    config.load(a)
    assert config.RELATIVE_WORKTREES is True
    config.load(b)
    assert config.RELATIVE_WORKTREES is False
    assert config.SSH_ALIAS == ""
    assert config.TICKET_PREFIXES is None


def test_zone_ids_distinguish_same_basename(tmp_path):
    assert gitidentity.zone_id_for(tmp_path / "a" / "work") != \
        gitidentity.zone_id_for(tmp_path / "b" / "work")


def test_zone_update_preserves_independent_settings():
    paths = platform.paths()
    scope = paths.home / "work"
    scope.mkdir()
    identity = gitidentity.upsert_zone(scope, "test@example.com", {"github.com": "work-gh"}, paths)
    extra = '\n[user]\n    signingkey = /example/key.pub\n[commit]\n    gpgsign = true\n'
    identity.write_text(identity.read_text() + extra)
    gitidentity.upsert_zone(scope, "test@example.com", {"gitlab.com": "work-gl"}, paths)
    assert extra in identity.read_text()


def test_false_fixer_not_counted_as_applied():
    assert sshdoctor.apply_fixes([
        sshdoctor.Finding("agent", "fix", "key", "not loaded", lambda: False)
    ]) == 0


@pytest.mark.parametrize("broken", [
    "# >>> grove:account=a >>>\nHost a\n",
    "# <<< grove:account=a <<<\n",
    "# >>> grove:account=a >>>\n# >>> grove:account=b >>>\n",
    "# >>> grove:account=a >>>\n# <<< grove:account=b <<<\n",
])
def test_inventory_rejects_invalid_markers(broken):
    with pytest.raises(ValidationError):
        blockedit.find_blocks(broken)


def test_duplicate_complete_markers_are_rejected():
    text = blockedit.upsert_block("", "account", "a", "Host a")
    with pytest.raises(ValidationError):
        blockedit.upsert_block(text + text, "account", "a", "Host new")


def test_legacy_zone_keeps_existing_include_and_filename():
    p = platform.paths()
    scope = p.home / 'legacy work'
    identity = p.identities_dir / 'work.gitconfig'
    blockedit.write_atomic(identity, gitidentity.render_identity('a@example.com', {'github.com': 'gh'}))
    original = blockedit.upsert_block('', 'zone', 'work',
        f'[includeIf "gitdir:{platform.normalize_gitdir(scope)}"]\n    path = "{identity}"')
    blockedit.write_atomic(p.gitconfig, original)
    assert gitidentity.upsert_zone(scope, 'a@example.com', {'gitlab.com': 'gl'}, p) == identity
    assert set(blockedit.find_blocks(p.gitconfig.read_text(), 'zone')) == {'work'}
    assert gitidentity.read_identity(identity)[1] == {'github.com': 'gh', 'gitlab.com': 'gl'}


def test_remove_last_account_keeps_signing_and_include():
    p = platform.paths()
    scope = p.home / 'work'
    identity = gitidentity.upsert_zone(scope, 'a@example.com', {'github.com': 'gh'}, p)
    identity.write_text(identity.read_text() + '\n[commit]\n    gpgsign = true\n')
    gitidentity.remove_account_from_zone(scope, 'gh', p)
    assert identity.is_file()
    assert 'gpgsign = true' in identity.read_text()
    assert gitidentity.read_identity(identity) == ('', {})
    assert blockedit.find_blocks(p.gitconfig.read_text(), 'zone')


def test_zone_conflict_is_rejected_before_generating_key(monkeypatch):
    from grove.core import sshprov
    p = platform.paths()
    scope = p.home / 'work'
    gitidentity.upsert_zone(scope, 'a@example.com', {'github.com': 'gh'}, p)
    monkeypatch.setattr(sshprov, '_keygen_if_missing', lambda *a, **kw: pytest.fail('keygen before validation'))
    with pytest.raises(ValidationError, match='email'):
        sshprov.add_account(sshprov.AddSpec('gl', 'gitlab.com', email='b@example.com', scope_dir=scope))


def test_zone_routing_conflict_does_not_overwrite():
    p = platform.paths()
    scope = p.home / 'work'
    identity = gitidentity.upsert_zone(scope, 'a@example.com', {'github.com': 'first'}, p)
    original = identity.read_bytes()
    with pytest.raises(ValidationError, match='another account'):
        gitidentity.upsert_zone(scope, 'a@example.com', {'github.com': 'second'}, p)
    assert identity.read_bytes() == original


def test_atomic_write_detects_concurrent_edit(tmp_path):
    target = tmp_path / 'config'
    target.write_text('new content')
    with pytest.raises(ValidationError, match='Concurrent'):
        blockedit.write_atomic(target, 'replacement', expected='old content')
    assert target.read_text() == 'new content'
    assert sorted(p.name for p in tmp_path.glob('.config.grove-*')) == ['.config.grove-lock']


def test_backups_are_unique_across_operations(tmp_path):
    target = tmp_path / 'config'
    target.write_text('first')
    with blockedit.edit_scope():
        first = blockedit.backup_once(target, tmp_path / 'backups')
        assert blockedit.backup_once(target, tmp_path / 'backups') is None
    target.write_text('second')
    with blockedit.edit_scope():
        second = blockedit.backup_once(target, tmp_path / 'backups')
    assert first != second
    assert first.read_text() == 'first'
    assert second.read_text() == 'second'


def test_doctor_rechecks_unsuccessful_callback(monkeypatch):
    from grove.core import doctor
    from grove.core.gitrunner import GitRunner
    issue = doctor.Issue('probe', 'auto', 'file', 'still broken', 'try', lambda: None)
    monkeypatch.setattr(doctor, 'diagnose', lambda *a: [issue])
    monkeypatch.setattr(doctor, 'skill_report', lambda *a: [])
    result = doctor.report(GitRunner(), None, fix=True)
    assert result['attempted'] == 1
    assert result['applied'] == 0
    assert result['remaining_issues'][0]['kind'] == 'probe'


def test_doctor_keeps_partial_failure_and_checks_other_repairs(monkeypatch):
    from grove.core import doctor
    from grove.core.gitrunner import GitRunner
    calls = []
    def failure():
        raise OSError('denied')
    issue = doctor.Issue('probe', 'auto', 'file', 'broken', 'try', failure)
    solved = doctor.Issue('other', 'auto', 'other', 'broken', 'try', lambda: calls.append(1))
    monkeypatch.setattr(doctor, 'diagnose', lambda *a: [issue])
    monkeypatch.setattr(doctor, 'skill_report', lambda *a: [])
    result = doctor.report(GitRunner(), None, issues=[issue, solved], fix=True)
    assert result['attempted'] == 2 and result['applied'] == 1
    assert result['failures'][0]['message'] == 'denied'
    assert calls == [1]


def test_mcp_doctor_dry_run_never_writes_missing_pointer(repo):
    from grove.mcp import _ops
    _, ctx = repo
    pointer = ctx.root / '.git'
    pointer.unlink()
    result = _ops.op_doctor(cwd=str(ctx.root), fix=True, dry_run=True)
    assert result['applied'] == result['attempted'] == 0
    assert not pointer.exists()
    assert any(i['kind'] == 'git-pointer' for i in result['issues'])


def test_cli_context_controls_compare_and_patch(repo, tmp_path, monkeypatch, capsys):
    _, ctx = repo
    monkeypatch.chdir(tmp_path)
    assert main(['compare', '-C', str(ctx.root / 'main'), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['result']['a'] == 'main'
    assert main(['patch', '-C', str(ctx.root / 'main'), '--stdout', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['result']['empty'] is True


def test_mcp_context_controls_default_reset_target(repo, tmp_path, monkeypatch):
    from grove.mcp import _ops
    _, ctx = repo
    monkeypatch.chdir(tmp_path)
    result = _ops.op_reset(cwd=str(ctx.root / 'main'), dry_run=True)
    assert result['worktree'] == 'main'


def test_policy_operations_serialize_and_restore():
    from concurrent.futures import ThreadPoolExecutor
    import time
    original = config.SSH_ALIAS
    @config.isolated_operation
    def run(alias):
        config.apply_policy({'ssh_alias': alias})
        time.sleep(.01)
        return config.SSH_ALIAS
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(run, ['a', 'b', 'a'])) == ['a', 'b', 'a']
    assert config.SSH_ALIAS == original


def test_failed_policy_operation_restores_defaults():
    @config.isolated_operation
    def fail():
        config.apply_policy({'ssh_alias': 'leaked'})
        raise ValueError('failed')
    with pytest.raises(ValueError):
        fail()
    @config.isolated_operation
    def next_call():
        return config.SSH_ALIAS
    assert next_call() == ''


def test_agent_empty_is_available_but_key_not_loaded(monkeypatch, tmp_path):
    from grove.core import sshprov, sshcheck
    key = tmp_path / 'key'
    key.write_text('key')
    monkeypatch.setattr(sshcheck, '_agent_fingerprints', lambda *a: (True, []))
    monkeypatch.setattr(sshcheck, '_fingerprint_of', lambda *a: 'SHA256:example')
    assert sshprov.key_status(sshprov.Account('a', 'example.com', str(key))).in_agent is False


def test_mcp_encrypted_key_generation_requires_terminal(tmp_path):
    from grove.mcp import _ops
    from grove.core.errors import UsageError
    with pytest.raises(UsageError, match='interactive terminal'):
        _ops.op_ssh_add('key', host='example.com', key=str(tmp_path / 'key'),
                        no_passphrase=False, no_identity=True)
    assert not (tmp_path / 'key').exists()


def test_agent_timeout_does_not_report_running(monkeypatch):
    import subprocess
    def timeout(*a, **kw):
        assert kw['timeout'] == 10
        raise subprocess.TimeoutExpired(a[0], 10)
    monkeypatch.setattr(platform.subprocess, 'run', timeout)
    assert platform.agent_running() is False
    assert platform.agent_add(Path('/missing/key')) is False


def test_gitconfig_path_honors_effective_global_override(monkeypatch, tmp_path):
    custom = tmp_path / 'elsewhere' / 'gitconfig'
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(custom))
    assert platform.paths().gitconfig == custom


def test_missing_identity_is_review_only():
    p = platform.paths()
    identity = gitidentity.upsert_zone(p.home / 'work', 'a@example.com', {'github.com': 'gh'}, p)
    identity.unlink()
    findings = sshdoctor.diagnose()
    assert any(f.check == 'missing-identity' and f.fixer is None for f in findings)


def test_effective_ssh_conflict_keeps_manual_block(tmp_path):
    from grove.core import sshprov
    p = platform.paths()
    key = tmp_path / 'key'
    key.write_text('fake key')
    manual = 'Host managed\n    HostName wrong.example.com\n\n'
    blockedit.write_atomic(p.ssh_config, manual)
    sshprov.add_account(sshprov.AddSpec('managed', 'github.com', key=key,
                                      no_identity=True, no_agent=True))
    assert any(f.check == 'effective-config' for f in sshdoctor.diagnose())
    assert p.ssh_config.read_text().startswith(manual)


def test_inventory_cli_mcp_parity(capsys):
    from grove.mcp import _ops
    assert main(['ssh', 'accounts', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['result'] == _ops.op_ssh_accounts()


def test_invalid_utf8_is_rejected_without_replacement(tmp_path):
    target = tmp_path / 'config'
    target.write_bytes(b'comment\xff\n')
    with pytest.raises(ValidationError, match='UTF-8'):
        blockedit.read_text(target)
    assert target.read_bytes() == b'comment\xff\n'


def test_normalized_zone_path_is_stable_without_resolving_symlinks(tmp_path):
    assert gitidentity.zone_id_for(tmp_path / 'a' / '..' / 'work') == gitidentity.zone_id_for(tmp_path / 'work')
    link = tmp_path / 'link'
    try:
        link.symlink_to(tmp_path / 'work', target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation unavailable')
    assert gitidentity.zone_id_for(link) != gitidentity.zone_id_for(tmp_path / 'work')


def test_two_zones_cannot_share_an_identity_file():
    p = platform.paths()
    scope = p.home / 'first'
    identity = gitidentity.upsert_zone(scope, 'a@example.com', {'github.com': 'gh'}, p)
    text = blockedit.upsert_block(p.gitconfig.read_text(), 'zone', 'second',
        f'[includeIf "gitdir:{platform.normalize_gitdir(p.home / "second")}"]\n    path = "{identity}"')
    p.gitconfig.write_text(text)
    original = identity.read_bytes()
    with pytest.raises(ValidationError, match='Ambiguous'):
        gitidentity.upsert_zone(scope, 'a@example.com', {'gitlab.com': 'gl'}, p)
    assert identity.read_bytes() == original
    assert any(f.check == 'ambiguous-zone' for f in sshdoctor.diagnose())


def test_relative_global_override_matches_neutral_git_cwd(monkeypatch):
    p = platform.paths()
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', 'relative.gitconfig')
    assert platform.paths().gitconfig == p.home / 'relative.gitconfig'


def test_global_config_uses_existing_xdg_file(monkeypatch):
    p = platform.paths()
    p.gitconfig.unlink()
    monkeypatch.delenv('GIT_CONFIG_GLOBAL')
    xdg = p.home / 'xdg'
    target = xdg / 'git' / 'config'
    target.parent.mkdir(parents=True)
    target.write_text('[user]\n    name = Example\n')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(xdg))
    assert platform.paths().gitconfig == target


def test_account_write_error_returns_json_with_recovery(monkeypatch, capsys, tmp_path):
    key = tmp_path / 'key'
    key.write_text('existing key')
    def failure(*a, **kw):
        raise OSError('cannot replace file')
    monkeypatch.setattr(blockedit, 'write_atomic', failure)
    assert main(['ssh', 'add', 'account', '--host', 'github.com', '--key', str(key),
                 '--no-identity', '--no-agent', '--json']) == 2
    response = json.loads(capsys.readouterr().out)
    assert response['status'] == 'error'
    assert 'inspect ssh accounts and ssh doctor' in response['message']


def test_remove_dry_run_includes_key_deletion_without_changes(tmp_path):
    from grove.core import sshprov
    p = platform.paths()
    key = tmp_path / 'key'
    key.write_text('existing key')
    sshprov.add_account(sshprov.AddSpec('account', 'github.com', key=key, no_identity=True, no_agent=True))
    original = p.ssh_config.read_bytes()
    result = sshprov.remove_account('account', delete_key=True, dry_run=True)
    assert any(step.startswith('delete key') for step in result['steps'])
    assert key.is_file() and p.ssh_config.read_bytes() == original


def test_unreferenced_zone_file_is_not_overwritten():
    p = platform.paths()
    scope = p.home / 'work'
    target = p.identities_dir / f'{gitidentity.zone_id_for(scope)}.gitconfig'
    blockedit.write_atomic(target, '[commit]\n    gpgsign = true\n')
    original = target.read_bytes()
    with pytest.raises(ValidationError, match='Unreferenced'):
        gitidentity.upsert_zone(scope, 'a@example.com', {'github.com': 'gh'}, p)
    assert target.read_bytes() == original


def test_remove_last_empty_zone_cleans_legacy_include():
    p = platform.paths()
    scope = p.home / 'work'
    target = p.identities_dir / 'legacy.gitconfig'
    blockedit.write_atomic(target, gitidentity.render_identity('a@example.com', {'github.com': 'gh'}))
    blockedit.write_atomic(p.gitconfig, blockedit.upsert_block('', 'zone', 'legacy',
        f'[includeIf "gitdir:{platform.normalize_gitdir(scope)}"]\n    path = "{target}"'))
    gitidentity.remove_account_from_zone(scope, 'gh', p)
    assert not target.exists()
    assert not blockedit.find_blocks(p.gitconfig.read_text(), 'zone')


def test_config_symlink_survives_atomic_edit(tmp_path):
    target = tmp_path / 'real-config'
    target.write_text('original')
    link = tmp_path / 'config'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('symlink creation unavailable')
    blockedit.write_atomic(link, 'changed', expected='original')
    assert link.is_symlink() and target.read_text() == 'changed'


@pytest.mark.parametrize('spec_dry,runner_dry', [(True, False), (False, True)])
def test_core_dry_run_is_safe_even_with_mismatched_runner(spec_dry, runner_dry):
    from grove.core import sshprov
    from grove.core.gitrunner import GitRunner
    p = platform.paths()
    before = {str(f.relative_to(p.home)): f.read_bytes() for f in p.home.rglob('*') if f.is_file()}
    result = sshprov.add_account(sshprov.AddSpec('account', 'github.com', email='a@example.com',
        scope_dir=p.home / 'work', dry_run=spec_dry), git=GitRunner(dry_run=runner_dry))
    after = {str(f.relative_to(p.home)): f.read_bytes() for f in p.home.rglob('*') if f.is_file()}
    assert before == after
    assert result['dry_run'] is True and result['agent_loaded'] is None


def test_relative_identity_include_is_reused():
    p = platform.paths()
    target = p.home / 'identity.gitconfig'
    target.write_text(gitidentity.render_identity('a@example.com', {'github.com': 'gh'}))
    scope = p.home / 'work'
    p.gitconfig.write_text(blockedit.upsert_block('', 'zone', 'legacy',
        f'[includeIf "gitdir:{platform.normalize_gitdir(scope)}"]\n    path = identity.gitconfig'))
    assert gitidentity.upsert_zone(scope, 'a@example.com', {'gitlab.com': 'gl'}, p) == target
    assert set(blockedit.find_blocks(p.gitconfig.read_text(), 'zone')) == {'legacy'}


@pytest.mark.parametrize('exception,message', [('missing', 'unavailable'), ('timeout', 'timed out')])
def test_identity_inspection_reports_process_failures(monkeypatch, tmp_path, exception, message):
    import subprocess
    def fail(*a, **kw):
        if exception == 'missing':
            raise FileNotFoundError('git')
        raise subprocess.TimeoutExpired(a[0], 10)
    monkeypatch.setattr(gitidentity.subprocess, 'run', fail)
    with pytest.raises(ValidationError, match=message):
        gitidentity.config_items('[user]\n    email = a@example.com\n')


def test_mcp_compare_uses_requested_worktree_when_a_is_omitted(repo, tmp_path, monkeypatch):
    from grove.mcp import _ops
    _, ctx = repo
    monkeypatch.chdir(tmp_path)
    assert _ops.op_compare(cwd=str(ctx.root / 'main'))['a'] == 'main'


def test_ssh_key_path_with_spaces_resolves_correctly(tmp_path):
    from grove.core import sshprov
    p = platform.paths()
    key = tmp_path / 'key with spaces'
    key.write_text('existing key')
    sshprov.add_account(sshprov.AddSpec('account', 'github.com', key=key, no_identity=True, no_agent=True))
    assert sshprov.read_inventory().accounts[0].key == str(key)
    assert not any(f.check == 'effective-config' for f in sshdoctor.diagnose())
