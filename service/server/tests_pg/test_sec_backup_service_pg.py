"""Complete backup entry point: real age, Git and isolated PG; fake GitHub transport only."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import cloud_runtime
import recovery_backup
import recovery_state
import sec_history
from test_sec_history_pg import seed, rows
from test_recovery_holds import initialize_empty, add_holds, seed_legacy, state


@pytest.mark.parametrize('push_fails', [False, True])
def test_backup_archive_remote_confirmation_before_retention(pg, tmp_path, monkeypatch, push_fails):
    seed(pg)
    initialize_empty()
    add_holds(['MSFT'])
    seed_legacy()
    portfolio = state()
    before = rows(pg)
    identity = tmp_path / 'identity'
    subprocess.run(['age-keygen', '-o', str(identity)], check=True, capture_output=True)
    recipient = subprocess.check_output(['age-keygen', '-y', str(identity)]).decode().strip()
    recipient_file = tmp_path / 'recipient'
    recipient_file.write_text(recipient)
    url_file = tmp_path / 'url'
    url_file.write_text(pg)
    repo = tmp_path / 'work' / 'repository'
    remote = tmp_path / 'off-server.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    expected = 'git@github.com:synthetic/isolated-recovery.git'
    original_command = recovery_backup.command

    def transport(*args, cwd=None):
        args = list(args)
        if args[:2] == ['git', 'clone']:
            original_command('git', 'clone', str(remote), args[3])
            original_command('git', 'remote', 'set-url', 'origin', expected, cwd=args[3])
            return b''
        if args[:3] == ['git', 'push', 'origin'] and push_fails:
            raise subprocess.CalledProcessError(1, ['git', 'push'])
        if args[0] == 'git' and args[1] in ('fetch', 'push', 'ls-remote'):
            args[2] = str(remote)
        return original_command(*args, cwd=cwd)

    monkeypatch.setattr(recovery_backup, 'command', transport)
    monkeypatch.setattr(recovery_backup.requests, 'get', lambda *a, **k: SimpleNamespace(status_code=404))
    monkeypatch.setattr('scanner_engine.set_service_status', lambda *a, **k: None)
    for name, value in dict(RECOVERY_WORKDIR=repo, RECOVERY_GITHUB_REPO='synthetic/isolated-recovery',
                            DATABASE_URL_FILE=url_file, AGE_RECIPIENT_FILE=recipient_file).items():
        monkeypatch.setenv(name, str(value))
    # backup() sets this process-wide variable; prevent it leaking to other tests.
    monkeypatch.setenv('GIT_SSH_COMMAND', '')
    if push_fails:
        with pytest.raises(subprocess.CalledProcessError):
            recovery_backup.backup()
        assert rows(pg) == before and not (repo.parent / 'status.json').exists()
    else:
        result = recovery_backup.backup()
        archive = result['sec_history']
        assert archive['format'] == 1 and archive['counts']['si_decisions'] == 2
        assert original_command('git', 'ls-remote', str(remote), 'refs/heads/main').decode().split()[0] == archive['remote_commit']
        manifest = json.loads(sec_history.decrypt(sec_history.location(repo, archive['manifest']), identity,
                                                 sec_history.MAX_MANIFEST_BYTES))
        assert manifest['counts'] == archive['counts']
        active = recovery_state.decrypt(next((repo / 'hourly').glob('*.age')), identity)
        assert len(active['hold_coverage']['order_ids']) == 1
        assert any(row['status'] == 'imported' for row in active['tables']['scanner_orders'])
        if hasattr(cloud_runtime, 'SEC_SCHEMA7_ROLLBACK_CAPABILITY'):
            assert archive['retention'] is None and rows(pg) == before
        else:
            assert archive['retention']['deleted']['si_decisions'] == 1
            assert archive['retention']['checkpoints_preserved']
        assert json.loads((repo.parent / 'status.json').read_text()) == result
    assert state() == portfolio  # neither archive nor retention debits/releases held cash
