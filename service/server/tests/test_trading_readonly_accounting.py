"""Synthetic accounting evidence; no model, provider, production DB or Telegram."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

from accounting_audit import reconcile


def load_script():
    path = Path(__file__).resolve().parents[3] / 'scripts' / 'trading_readonly_audit.py'
    spec = importlib.util.spec_from_file_location('synthetic_readonly_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(side='long'):
    trade = dict(id=1, agent_id=7, is_shadow=0, legacy_position_id=None,
                 side=side, entry_price=100., original_quantity=2.,
                 remaining_quantity=1., fees=.5, realized_pnl=10.)
    fills = {1: [dict(fill_type='entry', price=100., quantity=2., fee=.25, gross_pnl=0.),
                 dict(fill_type='tp', price=110. if side == 'long' else 90.,
                      quantity=1., fee=.25, gross_pnl=10.)]}
    account = dict(agent_id=7, initial_cash=1000., cash=909.5,
                   realized_pnl=10., fees_paid=.5)
    return [account], [trade], fills


def test_complete_native_history_matches_without_exposing_amounts():
    result = reconcile(*fixture())
    assert result['status'] == 'PASS'
    account = result['accounts'][0]
    assert {account[k]['status'] for k in ('cash', 'fees', 'realized')} == {'PASS'}
    assert result['native_fills']['status'] == 'PASS'
    assert result['native_fills']['checked'] == 1
    assert not any(word in json.dumps(result) for word in ('909.5', '1000.0', 'quantity_delta', 'cash_delta'))


def test_cash_only_import_baseline_is_unknown_even_when_aggregate_happens_to_match():
    accounts, trades, fills = fixture()
    result = reconcile(accounts, trades, fills, baseline={
        'cash_adjustment': 0., 'historical_performance_not_imported': True,
        'snapshot_id': 'synthetic-opening'})
    assert result['status'] == 'NOT_VERIFIED'
    assert result['accounts'][0]['cash']['status'] == 'PASS'
    for key in ('fees', 'realized'):
        assert result['accounts'][0][key] == {
            'status': 'NOT_VERIFIED', 'reason': 'OPENING_HISTORY_GAP'}
    assert result['native_fills']['status'] == 'PASS'


def test_omitted_closed_history_does_not_become_a_false_mismatch_or_an_invented_offset():
    accounts, trades, fills = fixture()
    accounts[0].update(cash=950., realized_pnl=55., fees_paid=5.)
    original = copy.deepcopy((accounts, trades, fills))
    result = reconcile(accounts, trades, fills, baseline={'cash_adjustment': 40.5})
    assert result['status'] == 'NOT_VERIFIED'
    assert result['accounts'][0]['cash']['status'] == 'PASS'
    assert result['accounts'][0]['fees']['reason'] == 'OPENING_HISTORY_GAP'
    assert result['accounts'][0]['realized']['reason'] == 'OPENING_HISTORY_GAP'
    assert (accounts, trades, fills) == original


@pytest.mark.parametrize('field,key', [('fees_paid', 'fees'), ('realized_pnl', 'realized'), ('cash', 'cash')])
def test_complete_history_account_mismatch_fails(field, key):
    accounts, trades, fills = fixture()
    accounts[0][field] += 1
    result = reconcile(accounts, trades, fills)
    assert result['status'] == 'FAIL'
    assert result['accounts'][0][key]['status'] == 'FAIL'


@pytest.mark.parametrize('field', ['remaining_quantity', 'fees', 'realized_pnl', 'original_quantity'])
def test_bad_native_fill_accounting_fails_independently_of_import_gap(field):
    accounts, trades, fills = fixture()
    trades[0][field] += 1
    result = reconcile(accounts, trades, fills, baseline={'cash_adjustment': 0.})
    assert result['status'] == 'FAIL'
    assert result['native_fills']['status'] == 'FAIL'
    assert result['accounts'][0]['fees']['status'] == 'NOT_VERIFIED'


def test_legacy_and_shadow_are_excluded_from_scanner_account_and_native_fill_scope():
    accounts, trades, fills = fixture()
    for trade_id, shadow, legacy in [(2, 1, None), (3, 0, 9)]:
        row = dict(trades[0], id=trade_id, is_shadow=shadow, legacy_position_id=legacy,
                   fees=999., realized_pnl=999.)
        trades.append(row)
        fills[trade_id] = []  # Legacy can lack historical entries; neither affects scanner account.
    result = reconcile(accounts, trades, fills)
    assert result['status'] == 'PASS'
    assert result['excluded'] == {'shadow_trades': 1, 'legacy_trades': 1}
    assert result['native_fills']['checked'] == 1


def test_short_collateral_flow_uses_entry_collateral_plus_realized_exit_value():
    assert reconcile(*fixture('short'))['status'] == 'PASS'


def test_empty_complete_account_is_valid_but_missing_or_clipped_scope_is_unknown():
    accounts = [dict(agent_id=7, initial_cash=100., cash=100., fees_paid=0., realized_pnl=0.)]
    assert reconcile(accounts, [], {})['status'] == 'PASS'
    assert reconcile([], [], {})['status'] == 'NOT_VERIFIED'
    assert reconcile(*fixture(), complete=False)['status'] == 'NOT_VERIFIED'


def test_other_accounts_do_not_leak_into_account_reconciliation():
    accounts, trades, fills = fixture()
    accounts.append(dict(agent_id=8, initial_cash=10., cash=10., fees_paid=0., realized_pnl=0.))
    assert reconcile(accounts, trades, fills)['status'] == 'PASS'


def test_unowned_native_trade_is_a_scope_failure():
    accounts, trades, fills = fixture()
    trades[0]['agent_id'] = 8
    assert reconcile(accounts, trades, fills)['status'] == 'FAIL'


@pytest.mark.parametrize('baseline', [{}, {'cash_adjustment': float('nan')}, {'cash_adjustment': 'bad'}])
def test_invalid_opening_baseline_is_not_silently_assumed_zero(baseline):
    result = reconcile(*fixture(), baseline=baseline)
    assert result['accounts'][0]['cash']['status'] == 'NOT_VERIFIED'
    assert result['accounts'][0]['cash']['reason'] == 'OPENING_BASELINE_INVALID'


def test_unknown_fill_kind_and_nonfinite_data_cannot_pass():
    accounts, trades, fills = fixture()
    fills[1][1]['fill_type'] = 'unsupported'
    assert reconcile(accounts, trades, fills)['native_fills']['status'] == 'FAIL'
    accounts, trades, fills = fixture()
    trades[0]['fees'] = float('nan')
    assert reconcile(accounts, trades, fills)['status'] == 'FAIL'


def original_fixture():
    accounts, trades, fills = fixture()
    accounts[0].update(cash=950., fees_paid=5., realized_pnl=55.)
    snapshot = dict(version=2, primary_agent_id=7, tables=dict(
        scanner_accounts=copy.deepcopy(accounts), scanner_trades=copy.deepcopy(trades),
        scanner_fills=[dict(f, trade_id=1) for f in fills[1]]))
    snapshot['snapshot_id'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    baseline = dict(snapshot_id=snapshot['snapshot_id'], cash_adjustment=40.5,
                    historical_performance_not_imported=True)
    return accounts, trades, fills, baseline, snapshot


def test_original_checksum_pinned_snapshot_proves_existing_account_without_mutation():
    accounts, trades, fills, baseline, snapshot = original_fixture()
    before = copy.deepcopy((accounts, trades, fills, baseline, snapshot))
    result = reconcile(accounts, trades, fills, baseline=baseline, opening_snapshot=snapshot)
    assert result['status'] == 'PASS'
    assert result['accounts'][0]['opening_evidence'] == 'CHECKSUM_AND_IMPORT_ID_VERIFIED'
    assert (accounts, trades, fills, baseline, snapshot) == before
    assert '40.5' not in json.dumps(result)


@pytest.mark.parametrize('field,key', [('fees_paid', 'fees'), ('realized_pnl', 'realized'), ('cash', 'cash')])
def test_mutated_current_totals_fail_despite_valid_original_proof(field, key):
    accounts, trades, fills, baseline, snapshot = original_fixture()
    accounts[0][field] += 1
    result = reconcile(accounts, trades, fills, baseline=baseline, opening_snapshot=snapshot)
    assert result['status'] == 'FAIL'
    assert result['accounts'][0][key]['status'] == 'FAIL'


@pytest.mark.parametrize('mutation,reason', [
    ('checksum', 'OPENING_SNAPSHOT_CHECKSUM_INVALID'),
    ('identity', 'OPENING_SNAPSHOT_ID_MISMATCH'),
    ('cash', 'OPENING_SNAPSHOT_CASH_BASELINE_MISMATCH')])
def test_invalid_original_evidence_never_turns_into_a_proven_offset(mutation, reason):
    accounts, trades, fills, baseline, snapshot = original_fixture()
    if mutation == 'checksum':
        snapshot['tables']['scanner_accounts'][0]['fees_paid'] += 1
    elif mutation == 'identity':
        baseline['snapshot_id'] = 'a' * 64
    else:
        baseline['cash_adjustment'] += 1
    result = reconcile(accounts, trades, fills, baseline=baseline, opening_snapshot=snapshot)
    assert result['accounts'][0]['fees'] == dict(status='NOT_VERIFIED', reason=reason)
    assert result['accounts'][0]['realized'] == dict(status='NOT_VERIFIED', reason=reason)


def test_claimed_provenance_fields_without_original_bytes_are_insufficient():
    accounts, trades, fills, baseline, _ = original_fixture()
    baseline.update(opening_adjustments_version=1, opening_adjustments_source='import_snapshot',
                    opening_adjustments_snapshot_id=baseline['snapshot_id'],
                    fees_paid_adjustment=4.5, realized_pnl_adjustment=45.)
    result = reconcile(accounts, trades, fills, baseline=baseline)
    assert result['accounts'][0]['fees']['status'] == 'NOT_VERIFIED'
    assert result['accounts'][0]['realized']['status'] == 'NOT_VERIFIED'


@pytest.mark.parametrize('case', ['duplicate_trade', 'duplicate_account', 'orphan_fill'])
def test_invalid_scope_cannot_double_count_or_discard_evidence(case):
    accounts, trades, fills = fixture()
    if case == 'duplicate_trade':
        trades.append(dict(trades[0]))
    elif case == 'duplicate_account':
        accounts.append(dict(accounts[0]))
    else:
        fills[99] = [dict(fills[1][0])]
    assert reconcile(accounts, trades, fills)['status'] == 'FAIL'


def test_importing_audit_does_not_open_database_or_initialize_workers(monkeypatch):
    import database
    monkeypatch.setattr(database, 'get_db_connection', lambda: pytest.fail('audit import opened database'))
    module = load_script()
    assert callable(module.main)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class ReadonlyConnection:
    def __init__(self, *, readonly='on', clipped=False):
        self.queries = []
        self.readonly = readonly
        self.clipped = clipped

    def execute(self, query):
        self.queries.append(query)
        if query == 'SHOW transaction_read_only':
            return Result([(self.readonly,)])
        if query == 'SHOW transaction_isolation':
            return Result([('repeatable read',)])
        accounts, trades, fills = fixture()
        if query.startswith('SELECT * FROM scanner_accounts'):
            return Result(accounts)
        if query.startswith('SELECT * FROM scanner_trades'):
            return Result(trades * (501 if self.clipped else 1))
        if query.startswith('SELECT trade_id,fill_type'):
            return Result([dict(f, trade_id=1) for f in fills[1]])
        if query.startswith('SELECT count(*) n FROM (SELECT event_key'):
            return Result([{'n': 0}])
        return Result([])


def test_collector_enforces_readonly_isolation_timeouts_and_bounded_inputs():
    module = load_script()
    conn = ReadonlyConnection()
    result = module.collect(conn)
    assert result['accounting']['status'] == 'PASS'
    assert conn.queries[:5] == [
        'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',
        "SET LOCAL statement_timeout='5s'", "SET LOCAL lock_timeout='2s'",
        'SHOW transaction_read_only', 'SHOW transaction_isolation']
    assert not any(query.startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE')) for query in conn.queries)
    assert result['natural_trading_e2e'] == 'NOT_VERIFIED'
    assert module.collect(ReadonlyConnection(clipped=True))['accounting']['status'] == 'NOT_VERIFIED'
    with pytest.raises(RuntimeError, match='requires_read_only'):
        module.collect(ReadonlyConnection(readonly='off'))


def test_original_reader_is_ram_only_bounded_and_keeps_stderr_private(tmp_path, monkeypatch):
    module = load_script()
    cipher = tmp_path / 'synthetic.age'
    identity = tmp_path / 'synthetic.identity'
    cipher.write_bytes(b'encrypted-fixture')
    identity.write_bytes(b'synthetic-protected-key')
    snapshot = original_fixture()[-1]
    raw = gzip.compress(json.dumps(snapshot).encode())

    class Decrypt:
        def __init__(self, args, **kwargs):
            assert args == ['age', '-d', '-i', str(identity), str(cipher)]
            assert kwargs['stderr'] == module.subprocess.DEVNULL
            self.stdout = io.BytesIO(raw)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stdout.close()

        def poll(self):
            return 0

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(module.subprocess, 'Popen', Decrypt)
    assert module.read_opening_snapshot(cipher, identity) == snapshot
    assert sorted(p.name for p in tmp_path.iterdir()) == ['synthetic.age', 'synthetic.identity']


def test_original_reader_limits_decompressed_output(tmp_path, monkeypatch):
    module = load_script()
    cipher, identity = tmp_path / 'synthetic.age', tmp_path / 'synthetic.identity'
    cipher.write_bytes(b'encrypted-fixture')
    identity.write_bytes(b'synthetic-key')

    class Decrypt:
        stdout = io.BytesIO(gzip.compress(b'x' * (16 * 1024 * 1024 + 1)))

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def poll(self):
            return 0

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(module.subprocess, 'Popen', Decrypt)
    with pytest.raises(ValueError, match='decompressed_too_large'):
        module.read_opening_snapshot(cipher, identity)
