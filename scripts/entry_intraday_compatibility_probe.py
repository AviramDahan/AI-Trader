"""CI-only image/format10 proof. No workers, providers or Production targets.

Invented candles and an explicit fixture clock feed the real image's discovery,
confirmation, admission, saved execution, emergency and recovery implementations.
The old74d image only seeds retained V1 state or refuses encrypted format10; it
never operates the supported current database after new contracts are created.
Only encrypted snapshots and sanitized PASS receipts leave disposable CI RAM.
"""
from __future__ import annotations

import copy
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from urllib.parse import urlparse

OLD_SHA = '74d09b2dba654bf29136a9b13020f36903c5dd3d'
PHASES = (
    'identity_bridge', 'identity_candidate', 'old_seed', 'candidate_preserve_v1',
    'candidate_intraday', 'bridge_creation_blocked', 'bridge_pending',
    'bridge_restart', 'candidate_emergency', 'bridge_emergency',
    'old_reader_refused10', 'bridge_restore10', 'bridge_restored_exits',
    'bridge_resume', 'bridge_expiry', 'bridge_final',
)
ROUTES = {
    'I_VCP': 'VCP_BASE_CONTRACTION',
    'I_BURST': 'STOCKBEE_MOMENTUM_BURST',
    'I_PULL': 'TREND_PULLBACK_RECLAIM',
    'I_RS': 'RELATIVE_STRENGTH_LEADER',
}
FLAGS = ('STOCK_SCANNER_VCP_DISCOVERY_ENABLED', 'STOCK_SCANNER_MOMENTUM_BURST_ENABLED',
         'STOCK_SCANNER_PEAD_ENABLED', 'STOCK_SCANNER_PULLBACK_RECLAIM_ENABLED',
         'STOCK_SCANNER_RS_LEADER_ENABLED', 'STOCK_SCANNER_INDEPENDENT_INTRADAY_ENABLED',
         'STOCK_SCANNER_INTRADAY_RVOL_CONTEXT_ENABLED')
STAMP = '2026-10-05T14:00:37+00:00'
UTC = timezone.utc
ROOT = Path('/proof')
DETAILS = {}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def isolated_url(value, phase):
    parsed = urlparse(value)
    expected = '/restored_intraday' if phase in ('bridge_restore10', 'bridge_restored_exits') else '/isolated_entry'
    if (parsed.scheme != 'postgresql' or parsed.hostname != 'entry-discovery-pg'
            or parsed.port != 5432 or parsed.username != 'isolated' or parsed.path != expected
            or parsed.query or parsed.fragment):
        raise ValueError('isolated_intraday_database_required')
    return parsed


def flags(active):
    for key in FLAGS:
        os.environ[key] = str(active).lower()
    # Runtime lies must never replace the immutable bridge build role.
    os.environ['ENTRY_DISCOVERY_ROLE'] = 'candidate'


def forbidden(*args, **kwargs):
    raise AssertionError('external_provider_io_forbidden')


def bootstrap(phase):
    global database, migrations, engine, recovery, initialize_empty, seed_legacy, record, state
    isolated_url(os.environ.get('DATABASE_URL', ''), phase)
    os.environ.update(STOCK_SCANNER_ENABLED='false', STOCK_SCANNER_TOKEN='synthetic-image-only',
        STOCK_SCANNER_TELEGRAM_ENABLED='false', TELEGRAM_NEWS_STREAM_ENABLED='false',
        STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED='false', SEC_INTELLIGENCE_MODE='off')
    for key in ('OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
        os.environ.pop(key, None)
    import requests
    import urllib.request
    import yfinance
    from curl_cffi import requests as curl_requests
    requests.sessions.Session.request = forbidden
    urllib.request.urlopen = forbidden
    yfinance.download = forbidden
    curl_requests.Session.request = forbidden
    sys.path[:0] = ['/fixtures/tests', '/fixtures/tests_pg']
    import database
    import migrations
    import scanner_engine as engine
    import recovery_state as recovery
    from test_recovery_holds import initialize_empty, seed_legacy, record, state
    flags(False)


def rows(query, args=()):
    with database.get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query, args)]


def order(ticker):
    values = rows("SELECT o.* FROM scanner_orders o JOIN scanner_signals s ON s.id=o.signal_id "
                  "WHERE s.ticker=? AND o.purpose='entry' ORDER BY o.id", (ticker,))
    assert len(values) == 1
    return values[0]


def saved(ticker):
    return json.loads(order(ticker)['plan_json'])


def checkpoint(name, value):
    # Private synthetic state only, on a tmpfs mount; not an uploaded artifact.
    (ROOT / (name + '.json')).write_text(json.dumps(value, sort_keys=True))


def read_checkpoint(name):
    return json.loads((ROOT / (name + '.json')).read_text())


def bar(ticker, price, minute=5, *, day='2026-10-05'):
    at = datetime.fromisoformat(f'{day}T14:{minute:02d}:00+00:00')
    value = dict(at=at.isoformat(), open=price, high=price+.05, low=price-.05, close=price)
    with patch.object(engine, 'now_z', return_value=(at+timedelta(minutes=5)).isoformat()):
        engine.process_bar(ticker, value)
    return value


def emergency_state():
    import entry_emergency
    with database.get_db_connection() as conn:
        return entry_emergency.snapshot(conn.cursor())


def identity(expected):
    import entry_discovery_capabilities as capabilities
    import entry_discovery
    assert capabilities.BUILD_ROLE == expected
    flags(True)
    assert capabilities.creation_allowed() == (expected == 'candidate')
    assert bool(entry_discovery.enabled_ids()) == (expected == 'candidate')
    file = Path(capabilities.__file__)
    assert os.geteuid() == 10001
    assert file.stat().st_uid == file.parent.stat().st_uid == 0
    assert file.stat().st_mode & 0o222 == 0 and not os.access(file.parent, os.W_OK)
    caps = capabilities.capabilities()
    assert 10 in caps['snapshot_formats']
    assert 'entry_discovery_intraday_v1' in caps['audit_versions']
    assert 'independent_entry_execution_intraday_v1' in caps['execution_versions']
    DETAILS.update(capabilities=caps, immutable_file_and_parent_verified=True,
                   role_module_sha256=hashlib.sha256(file.read_bytes()).hexdigest())


def candidate(ticker, strategy_id, *, decision_at=None):
    import entry_discovery as discovery
    import stock_scanner as scanner
    import single_target_policy
    import test_entry_intraday as fixtures
    decision = decision_at or fixtures.DECISION
    # A fresh invented witness for the paused-admission control, not a replayed
    # or fabricated real quote. The provider/network guards remain in force.
    with patch.object(fixtures, 'DECISION', decision), patch.object(fixtures, 'OBSERVED', decision-timedelta(seconds=60)):
        frame, context = fixtures.prior_case(strategy_id)
        return _confirmed_candidate(ticker, strategy_id, frame, context, decision, fixtures)


def _confirmed_candidate(ticker, strategy_id, frame, context, decision, fixtures):
    import entry_discovery as discovery
    import stock_scanner as scanner
    import single_target_policy
    context = copy.deepcopy(context)
    context['symbol'] = ticker
    cfg = scanner.settings() | {'entry_strategy_ids': [strategy_id], 'independent_intraday_enabled': True}
    candidates, observations = discovery.discover_candidates({ticker: frame},
        {ticker: {'company': 'Synthetic image fixture'}}, cfg,
        decision_at=decision, context=context, include_baseline=False)
    assert len(candidates) == 1 and candidates[0].get('_intraday_provisional'), observations
    provisional = candidates[0]
    witness, price, quote_at = fixtures.witness_for(provisional['_intraday_setups'][strategy_id])
    actual = discovery.confirm_intraday_candidate(provisional, witness, price=price,
        quote_at=quote_at, decision_at=decision)
    assert actual['strategy_ids'] == [strategy_id]
    package = actual['entry_discovery']
    assert package['version'] == discovery.INTRADAY_VERSION
    detection = package['detections'][0]
    assert detection['state'] == 'DETECTED'
    assert detection['features']['relative_volume']['status'] == 'VERIFIED'
    assert detection['features']['relative_volume']['prior_session_count'] == 10
    assert discovery.validate_candidate_trigger(actual, price, quote_at, decision)
    # Explicit invented chart anchors feed the unchanged real structural policy.
    # This isolates binary contract behavior, NOT scanner quality or historical profit.
    zones = [dict(low=price-3, high=price-2.8,
                  pivots=[dict(confirmed_at='2026-10-01T20:05:00+00:00')]),
             dict(low=price+8, high=price+8.4,
                  pivots=[dict(confirmed_at='2026-10-01T20:05:00+00:00')])]
    plan = single_target_policy.build(price, 1, zones, '2026-10-02', decision.isoformat())
    assert plan['minimum_rr'] == 2 and plan['rr'][0] >= 2
    signal = dict(ticker=ticker, company='Synthetic image fixture', action='BUY', entry=price,
        stop_loss=plan['stop'], target_plan=plan, quote_at=quote_at, confidence=.91,
        time_horizon='days', reason='Synthetic image lifecycle only; no market or AI outcome', relevant_news=[])
    return signal, actual


def create(ticker, strategy_id='VCP_BASE_CONTRACTION'):
    signal, source = candidate(ticker, strategy_id)
    with patch.object(engine, 'now_z', return_value=STAMP):
        result = engine.record_signal(signal, source, {}, {}, 'isolated-intraday-image')
    assert result['status'] == 'PENDING_ENTRY', result
    contract = saved(ticker)
    assert contract['entry_discovery'] == source['entry_discovery']
    assert contract['entry_strategy_execution']['version'] == 'independent_entry_execution_intraday_v1'
    return contract


def same_attribution(ticker):
    contract = saved(ticker)
    technical = json.loads(rows('SELECT technical_json FROM scanner_signals WHERE ticker=?', (ticker,))[0]['technical_json'])
    assert technical['entry_discovery'] == contract['entry_discovery']
    assert technical['entry_strategy_execution'] == contract['entry_strategy_execution']
    for trade in rows('SELECT settings_json FROM scanner_trades WHERE ticker=?', (ticker,)):
        settings = json.loads(trade['settings_json'])
        assert settings['entry_discovery'] == contract['entry_discovery']
        assert settings['entry_strategy_execution'] == contract['entry_strategy_execution']


def unchanged_holds():
    assert state()['holds'] == read_checkpoint('retained-holds')


def backup10():
    data = recovery.export_postgres(os.environ['DATABASE_URL'])
    assert data['version'] == data['recovery_format'] == 10
    assert len(data['hold_coverage']['order_ids']) == len(state()['holds']) >= 2
    key = ROOT / 'synthetic-age-identity'
    subprocess.run(['age-keygen', '-o', str(key)], check=True, capture_output=True)
    recipient = subprocess.check_output(['age-keygen', '-y', str(key)]).decode().strip()
    encrypted, sizes = recovery.encrypted_bytes(data, recipient)
    artifact = ROOT / 'intraday10.age'
    artifact.write_bytes(encrypted)
    assert recovery.decrypt(artifact, key) == data  # decrypt only in process RAM
    active = state()
    for key, table in (('trades', 'scanner_trades'), ('fills', 'scanner_fills')):
        ids = {row['id'] for row in data['tables'][table]}
        active[key] = [row for row in active[key] if row['id'] in ids]
    reserved = sum(row['limit_price']*row['quantity'] for row in data['tables']['scanner_orders']
                   if row['status'] in ('pending', 'recovery_uncertain') and row['purpose'] == 'entry')
    assert reserved == data['hold_coverage']['entry_reserved_notional']
    active['reserved'] = [{'amount': reserved}]
    checkpoint('restored-core', active)
    checkpoint('paused-control', emergency_state())
    DETAILS.update(recovery_format=10, encrypted_bytes=sizes['encrypted_bytes'],
                   encrypted_sha256=hashlib.sha256(encrypted).hexdigest(),
                   hold_count=len(data['hold_coverage']['order_ids']))


def run(phase):
    if phase in ('identity_bridge', 'identity_candidate'):
        identity(phase.removeprefix('identity_'))
    elif phase == 'old_seed':
        assert os.environ.get('BUILD_SHA') == OLD_SHA
        migrations.migrate()
        initialize_empty()
        seed_legacy()
        with patch.object(engine, 'now_z', return_value=STAMP):
            assert record('V1_ACTIVE')['status'] == 'PENDING_ENTRY'
            assert record('V1_HELD')['status'] == 'PENDING_ENTRY'
        bar('V1_ACTIVE', 100)
        with database.get_db_connection() as conn:
            conn.execute("UPDATE scanner_orders SET status='recovery_uncertain' WHERE signal_id="
                         "(SELECT id FROM scanner_signals WHERE ticker='V1_HELD')")
            conn.execute("UPDATE scanner_signals SET status='RECOVERY_UNCERTAIN' WHERE ticker='V1_HELD'")
            conn.commit()
        assert {r['strategy'] for r in rows("SELECT strategy FROM scanner_trades WHERE ticker='V1_ACTIVE'")} == {'single', 'staged'}
        assert recovery.export_postgres(os.environ['DATABASE_URL'])['version'] == 2
        checkpoint('old-core', state())
        DETAILS['recovery_format'] = 2
    elif phase == 'candidate_preserve_v1':
        identity('candidate'); flags(False)
        before = read_checkpoint('old-core')
        assert state() == before
        engine.initialize_runtime()
        assert state() == before
        DETAILS['retained_v1_and_legacy_unchanged'] = True
    elif phase == 'candidate_intraday':
        identity('candidate')
        for ticker, strategy_id in ROUTES.items():
            create(ticker, strategy_id)
        for ticker in ('I_HELD', 'I_EXPIRE', 'I_WAIT'):
            create(ticker)
        assert not rows("SELECT f.id FROM scanner_fills f JOIN scanner_trades t ON t.id=f.trade_id WHERE t.ticker LIKE 'I_%'")
        create_signal, create_source = candidate('BRIDGE_REJECT', 'VCP_BASE_CONTRACTION')
        checkpoint('new-admission', [create_signal, create_source])
        # Natural missing-candle uncertainty is retained, not converted to a fill.
        with patch.object(engine, 'now_z', return_value='2026-10-05T14:20:00+00:00'):
            engine._pending_recovery_check('I_HELD', [], datetime(2026, 10, 5, 14, 20, tzinfo=UTC))
        assert order('I_HELD')['status'] == 'recovery_uncertain'
        checkpoint('retained-holds', state()['holds'])
        checkpoint('candidate-core', state())
        DETAILS['actual_confirmed_routes'] = sorted(ROUTES.values())
    elif phase == 'bridge_creation_blocked':
        identity('bridge')  # deliberately flags ON and forged runtime role
        import entry_discovery
        assert entry_discovery.enabled_ids() == ()
        signal, source = read_checkpoint('new-admission')
        before = state()
        try:
            with patch.object(engine, 'now_z', return_value=STAMP):
                engine.record_signal(signal, source, {}, {}, 'forbidden-bridge')
        except ValueError as exc:
            assert str(exc) == 'new_entry_discovery_disabled'
        else:
            raise AssertionError('bridge_creation_not_rejected')
        assert state() == before == read_checkpoint('candidate-core')
        DETAILS['actual_new_creation_rejected_with_flags_on'] = True
    elif phase == 'bridge_pending':
        identity('bridge'); flags(False)
        before = state()
        engine.initialize_runtime()
        assert state() == before
        for ticker in ROUTES:
            contract = saved(ticker)
            support = contract['entry_strategy_execution']['branches'][0]['support']
            bar(ticker, support-.05)
            assert order(ticker)['status'] == 'pending'
            assert saved(ticker)['last_strategy_entry_block']['reason'] == 'strategy_fill_below_support'
            bar(ticker, order(ticker)['limit_price'], 10)
            assert order(ticker)['status'] == 'filled'
            assert rows("SELECT status FROM scanner_trades WHERE ticker=?", (ticker,)) == [{'status': 'open'}]
            same_attribution(ticker)
        unchanged_holds()
        checkpoint('after-fill', state())
        DETAILS['four_frozen_bad_price_rejected_then_good_filled'] = True
    elif phase == 'bridge_restart':
        identity('bridge'); flags(False)
        before = state()
        assert before == read_checkpoint('after-fill')
        engine.initialize_runtime()
        assert state() == before
        for ticker in ROUTES:
            bar(ticker, order(ticker)['limit_price'], 10)
        assert state() == before
        unchanged_holds()
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        DETAILS['restart_no_duplicate_entry'] = True
    elif phase == 'candidate_emergency':
        identity('candidate')
        import entry_emergency as emergency
        assert emergency_state() == emergency.initial()
        create('I_PAUSED')
        with patch.object(engine, 'now_z', return_value=STAMP):
            assert record('V1_PAUSED')['status'] == 'PENDING_ENTRY'
        paused = emergency.set_paused(True, 0, now=datetime(2026, 10, 5, 14, 16, tzinfo=UTC))
        before = state()
        signal, source = candidate('PAUSED_REJECT', 'VCP_BASE_CONTRACTION',
            decision_at=datetime(2026, 10, 5, 14, 15, 37, tzinfo=UTC))
        try:
            with patch.object(engine, 'now_z', return_value='2026-10-05T14:17:00Z'):
                engine.record_signal(signal, source, {}, {}, 'paused-creation')
        except ValueError as exc:
            assert str(exc) == 'entry_emergency_paused'
        else:
            raise AssertionError('paused_creation_not_rejected')
        assert state() == before
        checkpoint('paused-control', paused)
        checkpoint('pre-paused-bridge', before)
    elif phase == 'bridge_emergency':
        identity('bridge'); flags(False)
        before = state()
        assert before == read_checkpoint('pre-paused-bridge')
        engine.initialize_runtime()
        assert state() == before and emergency_state() == read_checkpoint('paused-control')
        for ticker in ('I_PAUSED', 'V1_PAUSED', 'I_WAIT'):
            initial = order(ticker)
            bar(ticker, initial['limit_price'], 20)
            assert order(ticker) == initial
        assert state() == before
        # Real TP and SL transitions continue while new/pending entries stop.
        bar('I_VCP', saved('I_VCP')['target_plan']['active_target'], 20)
        bar('I_BURST', saved('I_BURST')['target_plan']['stop']-.1, 20)
        for ticker in ('I_VCP', 'I_BURST'):
            assert rows('SELECT status FROM scanner_trades WHERE ticker=?', (ticker,)) == [{'status': 'closed'}]
        unchanged_holds()
        backup10()
        checkpoint('after-snapshot', state())
        DETAILS['pause_blocks_entries_tp_sl_continue'] = True
    elif phase == 'old_reader_refused10':
        assert os.environ.get('BUILD_SHA') == OLD_SHA
        try:
            recovery.decrypt(ROOT/'intraday10.age', ROOT/'synthetic-age-identity')
        except ValueError as exc:
            assert str(exc) == 'not_a_recovery_snapshot'
        else:
            raise AssertionError('old74d_must_refuse_format10')
        DETAILS.update(backup_formats_rejected=[10], old_runtime_not_a_supported_rollback=True)
    elif phase == 'bridge_restore10':
        identity('bridge'); flags(False)
        migrations.migrate()
        assert rows('SELECT count(*) n FROM agents') == [{'n': 0}]
        data = recovery.decrypt(ROOT/'intraday10.age', ROOT/'synthetic-age-identity')
        assert data['version'] == data['recovery_format'] == 10
        recovery.restore(data, os.environ['DATABASE_URL'], 'synthetic-intraday-image-token-longer-than-32')
        del data  # no plaintext snapshot file is created
        engine.initialize_runtime()
        assert state() == read_checkpoint('restored-core')
        assert emergency_state() == read_checkpoint('paused-control')
        assert rows('SELECT count(*) n FROM scanner_telegram_outbox') == [{'n': 0}]
        unchanged_holds()
        for ticker in ('I_PULL', 'I_RS'):
            same_attribution(ticker)
        DETAILS['ram_restore_empty_pg_preserves_pause_holds_attribution'] = True
    elif phase == 'bridge_restored_exits':
        identity('bridge'); flags(False)
        before = state()
        for ticker, price in (('I_PULL', saved('I_PULL')['target_plan']['active_target']),
                              ('I_RS', saved('I_RS')['target_plan']['stop']-.1)):
            bar(ticker, price, 25)
            assert rows('SELECT status FROM scanner_trades WHERE ticker=?', (ticker,)) == [{'status': 'closed'}]
        assert len(state()['fills']) == len(before['fills'])+2
        after = state()
        engine.initialize_runtime()
        bar('I_PULL', saved('I_PULL')['target_plan']['active_target'], 25)
        assert state() == after
        unchanged_holds()
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        DETAILS['restored_tp_sl_no_duplicate_and_holds_preserved'] = True
    elif phase == 'bridge_resume':
        identity('bridge'); flags(False)
        import entry_emergency as emergency
        assert state() == read_checkpoint('after-snapshot')  # SAME unrewound source DB
        resumed = emergency.set_paused(False, 1, now=datetime(2026, 10, 5, 14, 27, tzinfo=UTC))
        ticker = 'I_PAUSED'
        bar(ticker, order(ticker)['limit_price'], 25)
        assert order(ticker)['status'] == 'pending'  # straddles resume
        engine.initialize_runtime()
        bar(ticker, order(ticker)['limit_price'], 30)
        assert order(ticker)['status'] == 'filled'
        after = state()
        engine.initialize_runtime()
        bar(ticker, order(ticker)['limit_price'], 30)
        assert state() == after and emergency_state() == resumed
        unchanged_holds()
        DETAILS['same_db_resume_no_retroactive_or_duplicate_fill'] = True
    elif phase == 'bridge_expiry':
        identity('bridge'); flags(False)
        before = state()
        bar('I_EXPIRE', order('I_EXPIRE')['limit_price'], 5, day='2026-10-06')
        assert order('I_EXPIRE')['status'] == 'expired'
        assert not rows('SELECT id FROM scanner_trades WHERE ticker=?', ('I_EXPIRE',))
        assert state()['fills'] == before['fills']
        unchanged_holds()
        DETAILS['expiry_never_extends_or_fills_frozen_order'] = True
    elif phase == 'bridge_final':
        identity('bridge'); flags(False)
        before = state()
        engine.initialize_runtime()
        assert state() == before
        unchanged_holds()
        assert len(rows('SELECT id FROM scanner_fills')) == len({r['id'] for r in rows('SELECT id FROM scanner_fills')})
        original = read_checkpoint('old-core')
        # No unrelated V1 trade/fill or original adopted position was rewritten
        # while the new contracts entered/exited on the SAME current database.
        for key in ('trades', 'fills', 'legacy_positions'):
            expected = {row['id']: row for row in original[key]}
            actual = {row['id']: row for row in state()[key] if row['id'] in expected}
            assert actual == expected
        assert rows("SELECT count(*) n FROM scanner_orders WHERE purpose='entry' AND status='recovery_uncertain'")[0]['n'] == 2
        assert recovery.export_postgres(os.environ['DATABASE_URL'])['version'] == 10
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        DETAILS.update(accounting_ok=True, retained_hold_count=2, current_db_never_rewound=True,
                       retained_v1_and_legacy_unchanged=True,
                       no_production_activation=True, no_empirical_performance_claim=True)
    else:
        raise ValueError('unsupported_test_phase')


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in PHASES:
        raise SystemExit('exact_intraday_test_phase_required')
    phase = sys.argv[1]
    # Imported application/fixture libraries may log to stdout. Preserve every
    # message on stderr; stdout is the strict one-receipt-per-phase protocol.
    # Exceptions still propagate, so a failed phase emits no PASS receipt.
    with redirect_stdout(sys.stderr):
        bootstrap(phase)
        run(phase)
    print(json.dumps(dict(version=1, phase=phase, status='PASS',
        build_sha=os.environ.get('BUILD_SHA'), probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        **DETAILS), sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
