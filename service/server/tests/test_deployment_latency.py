"""Latency regressions without removing release/backup security gates."""
from collections.abc import Mapping
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sec_history as history
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import readiness_pg_shards as shards

ROOT = Path(__file__).resolve().parents[3]


def decision(**extra):
    row = dict.fromkeys(history.REQUIRED_COLUMNS['si_decisions'])
    row.update(scan_id='synthetic', ticker='SYNTH', mode='paper', **extra)
    return row


def test_readiness_regression_parallel_with_unchanged_real_pg_environment():
    jobs = yaml.safe_load((ROOT / '.github/workflows/cloud-readiness.yml').read_text())['jobs']
    regression = jobs['backend']
    pg = jobs['postgres']
    assert not regression.get('needs') and not pg.get('needs')
    assert not regression.get('if') and not pg.get('if')
    assert regression['services'] == pg['services']
    assert regression['env'] == pg['env']
    assert regression['runs-on'] == pg['runs-on']
    commands = [step.get('run', '') for step in regression['steps']]
    assert commands[-1] == 'python -m pytest service/server/tests -q'
    assert any('postgresql-client-17 age' in command for command in commands)
    assert pg['strategy'] == {'fail-fast': False, 'matrix': {'shard': [0, 1]}}
    assert any(step.get('run') == 'python scripts/readiness_pg_shards.py --index ${{ matrix.shard }} --count 2'
               for step in pg['steps'])
    assert all('service/server/tests -q' not in step.get('run', '') for step in pg['steps'])
    assert 'cancel-in-progress: false' in (ROOT / '.github/workflows/hetzner-deploy.yml').read_text()


def test_pg_partitions_are_complete_disjoint_nonempty_and_deterministic():
    parts = shards.partition(ROOT, 2)
    suite = ROOT / 'service/server/tests_pg'
    expected = {p.relative_to(ROOT).as_posix()
                for p in {*suite.rglob('test_*.py'), *suite.rglob('*_test.py')}}
    assert all(parts) and set(parts[0]).isdisjoint(parts[1])
    assert set(parts[0]) | set(parts[1]) == expected
    assert parts == shards.partition(ROOT, 2)


@pytest.mark.parametrize('count', [0, -1, True, 0.5, 100000])
def test_pg_partition_cannot_silently_run_empty_suite(count):
    with pytest.raises(ValueError):
        shards.partition(ROOT, count)


def test_pg_runner_propagates_test_failure_and_uses_all_selected_files(monkeypatch):
    calls = []
    monkeypatch.setattr(shards.pytest, 'main', lambda command, **kw: calls.append((command, kw)) or 7)
    assert shards.main(['--index', '1', '--count', '2']) == 7
    assert calls[0][0] == [str(ROOT / 'service/server/tests_pg'), '-q', '--durations=15']
    plugin = calls[0][1]['plugins'][0]
    assert plugin.index == 1 and plugin.parts == shards.partition(ROOT, 2)


@pytest.mark.parametrize('index', [-1, 2])
def test_pg_runner_rejects_wrong_shard_before_execution(monkeypatch, index):
    monkeypatch.setattr(shards.pytest, 'main', lambda *a, **kw: pytest.fail('invalid shard executed'))
    with pytest.raises(SystemExit):
        shards.main(['--index', str(index), '--count', '2'])


def test_actual_collected_node_ids_partition_without_loss_or_overlap(capsys):
    parts = [['service/server/tests_pg/test_a.py'], ['service/server/tests_pg/test_b.py']]
    original = [SimpleNamespace(nodeid=file + '::test_case[' + str(n) + ']')
                for part in parts for file in part for n in range(3)]
    selected, rejected = [], []
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda **kw: rejected.append(kw['items'])))
    for index in range(2):
        items = list(original)
        shards.ShardCollection(parts, index).pytest_collection_modifyitems(config, items)
        selected.append({item.nodeid for item in items})
    assert not selected[0] & selected[1]
    assert selected[0] | selected[1] == {item.nodeid for item in original}
    assert {item.nodeid for item in rejected[0]} == selected[1]
    assert '"full_count": 6' in capsys.readouterr().out


@pytest.mark.parametrize('case', ['unknown', 'duplicate', 'empty', 'overlap'])
def test_collection_errors_do_not_silently_drop_tests(case):
    parts = [['a.py'], ['b.py']]
    ids = ['a.py::test_one', 'b.py::test_two']
    if case == 'unknown': ids.append('new.py::test_new')
    if case == 'duplicate': ids.append(ids[0])
    if case == 'empty': ids.pop()
    if case == 'overlap': parts[1].append('a.py')
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda **kw: None))
    with pytest.raises(pytest.UsageError):
        shards.ShardCollection(parts, 0).pytest_collection_modifyitems(
            config, [SimpleNamespace(nodeid=node) for node in ids])


def test_non_secret_environment_values_not_decoded_per_archive_row():
    lookups = []

    class Environment(Mapping):
        def __iter__(self):
            return iter(['PUBLIC_SETTING_' + str(i) for i in range(200)] + ['INTERNAL_SECRET'])

        def __len__(self):
            return 201

        def __getitem__(self, name):
            lookups.append(name)
            return 'synthetic-secret-value-not-present'

    row = decision()
    with patch.object(history.os, 'environ', Environment()):
        assert history.row_valid('si_decisions', row) == history.encoded(row)
    assert len(lookups) == 1, 'irrelevant environment values decoded per row'


@pytest.mark.parametrize('name', ['TOKEN', 'PASSWORD', 'SECRET', 'API_KEY', 'PREFIX_API_KEY_SUFFIX'])
def test_secret_checks_are_live_not_cached_across_rows(monkeypatch, name):
    secret = 'synthetic-sensitive-value-123456789'
    row = decision(rejection_reason=secret)
    with patch.dict(os.environ, {}, clear=True):
        history.row_valid('si_decisions', row)
        monkeypatch.setenv(name, secret)
        with pytest.raises(ValueError, match='environment_secret_in_sec_archive'):
            history.row_valid('si_decisions', row)
        monkeypatch.setenv(name, 'changed-sensitive-value-987654321')
        history.row_valid('si_decisions', row)


@pytest.mark.parametrize('value', ['postgresql://synthetic', '-----BEGIN SYNTHETIC PRIVATE KEY'])
def test_generic_secret_patterns_still_block(value):
    with pytest.raises(ValueError, match='secret_pattern_in_sec_archive'):
        history.row_valid('si_decisions', decision(rejection_reason=value))


def test_exact_encoded_bytes_and_identity_guards_unchanged():
    row = decision(rejection_reason='synthetic unicode \u05d0', baseline_rank_score=0.5)
    assert history.row_valid('si_decisions', row) == history.encoded(row)
    row['ticker'] = ''
    with pytest.raises(ValueError, match='identity_invalid'):
        history.row_valid('si_decisions', row)


def test_row_size_and_status_guards_unchanged(monkeypatch):
    monkeypatch.setattr(history, 'MAX_ROW_BYTES', 10)
    with pytest.raises(ValueError, match='row_too_large'):
        history.row_valid('si_decisions', decision())
    monkeypatch.setattr(history, 'MAX_ROW_BYTES', 1024 * 1024)
    row = dict.fromkeys(history.REQUIRED_COLUMNS['si_filing_jobs'])
    row.update(accession='synthetic', status='unrecognized')
    with pytest.raises(ValueError, match='status_invalid'):
        history.row_valid('si_filing_jobs', row)
