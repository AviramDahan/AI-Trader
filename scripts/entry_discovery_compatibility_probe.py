"""CI-only real application-image proof on disposable PostgreSQL, never workers.

Only fixture candles/clock/provider IO are synthetic. Every reader, admission,
fill, recovery, migration and exit implementation is imported from its image.
The old runtime runs ONLY on an isolated clone: it is NOT a rollback target.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlparse

PHASE = sys.argv[1]
URL = os.environ.get('DATABASE_URL', '')
parsed = urlparse(URL)
if (parsed.scheme != 'postgresql' or parsed.hostname != 'entry-discovery-pg' or
        parsed.username != 'isolated' or parsed.path not in
        ('/isolated_entry', '/restored_entry', '/restored_audit', '/restored_emergency', '/unsafe_entry')):
    raise SystemExit('isolated_entry_database_required')
if PHASE == 'old_runtime_unsafe' and parsed.path != '/unsafe_entry':
    raise SystemExit('old_runtime_requires_disposable_clone')
if parsed.path == '/unsafe_entry' and PHASE != 'old_runtime_unsafe':
    raise SystemExit('clone_is_only_for_unsupported_old_runtime')

os.environ.update(STOCK_SCANNER_ENABLED='false', STOCK_SCANNER_TOKEN='synthetic-image-only',
    STOCK_SCANNER_TELEGRAM_ENABLED='false', TELEGRAM_NEWS_STREAM_ENABLED='false',
    STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED='false', SEC_INTELLIGENCE_MODE='off')
for key in ('OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
    os.environ.pop(key, None)
import requests
def forbidden(*args, **kwargs):
    raise AssertionError('external_provider_io_forbidden')
requests.sessions.Session.request = forbidden
import yfinance
yfinance.download = forbidden
from curl_cffi import requests as curl_requests
curl_requests.Session.request = forbidden
sys.path[:0] = ['/fixtures/tests', '/fixtures/tests_pg']
import database
import migrations
import scanner_engine as engine
import recovery_state as recovery
from test_recovery_holds import initialize_empty, seed_legacy, record, state

ROOT = Path('/proof')
STAMP = '2026-10-06T14:00:37+00:00'
DETAILS = {}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def rows(query, args=()):
    with database.get_db_connection() as conn:
        return [dict(row) for row in conn.execute(query, args)]


def order(ticker):
    return rows('SELECT o.* FROM scanner_orders o JOIN scanner_signals s ON s.id=o.signal_id '
                'WHERE s.ticker=? AND o.purpose=\'entry\' ORDER BY o.id LIMIT 1', (ticker,))[0]


def stored(ticker):
    return json.loads(order(ticker)['plan_json'])


def emergency_state():
    import entry_emergency
    with database.get_db_connection() as conn:
        return entry_emergency.snapshot(conn.cursor())


def bar(ticker, price, minute=5):
    value = dict(at=f'2026-10-06T14:{minute:02d}:00+00:00', open=price,
                 high=price+.1, low=price-.1, close=price)
    with patch.object(engine, 'now_z', return_value=f'2026-10-06T14:{minute+5:02d}:00+00:00'):
        engine.process_bar(ticker, value)
    return value


def flags(active):
    # The role must remain immutable even if this runtime environment lies.
    for flag in ('STOCK_SCANNER_VCP_DISCOVERY_ENABLED', 'STOCK_SCANNER_MOMENTUM_BURST_ENABLED',
                 'STOCK_SCANNER_PEAD_ENABLED', 'STOCK_SCANNER_PULLBACK_RECLAIM_ENABLED',
                 'STOCK_SCANNER_RS_LEADER_ENABLED'):
        os.environ[flag] = str(active).lower()
    os.environ['ENTRY_DISCOVERY_ROLE'] = 'candidate'


def identity(expected):
    import entry_discovery_capabilities as capabilities
    assert capabilities.BUILD_ROLE == expected
    flags(True)
    assert capabilities.creation_allowed() == (expected == 'candidate')
    # IMAGE_IMMUTABILITY_BEGIN (Linux images only; source-smoke cannot claim this)
    role_file = Path(capabilities.__file__)
    assert os.geteuid() == 10001
    assert role_file.stat().st_uid == role_file.parent.stat().st_uid == 0
    assert role_file.stat().st_mode & 0o222 == 0
    assert not os.access(role_file.parent, os.W_OK)  # no unlink/rename replacement
    DETAILS['immutable_file_and_parent_verified'] = True
    # IMAGE_IMMUTABILITY_END
    DETAILS['capabilities'] = capabilities.capabilities()
    DETAILS['role_module_sha256'] = hashlib.sha256(Path(capabilities.__file__).read_bytes()).hexdigest()


def candidate(ticker, strategy_id, *, baseline=False):
    import stock_scanner as scanner
    import entry_discovery as discovery
    from test_entry_strategies_integration import route_case
    from test_signal_inputs import Clock
    frame, context, decision, observed = route_case(strategy_id, executable_structure=True)
    context = copy.deepcopy(context)
    context['symbol'] = ticker
    for event in context.get('earnings_events', []):
        event['symbol'] = ticker
    Clock.instant = decision
    cfg = scanner.settings() | {'entry_strategy_ids': [strategy_id]}
    # Baseline contributor is a genuinely calculated candidate, not a fabricated
    # DETECTED record. It creates the retained audit-only shape (no execution key).
    with patch.object(scanner, 'datetime', Clock):
        candidates, observations = discovery.discover_candidates({ticker: frame},
            {ticker: {'company': 'Synthetic image fixture'}}, cfg, decision_at=decision,
            context=context, include_baseline=baseline)
        assert len(candidates) == 1, observations
        result = candidates[0]
        assert (discovery.BASELINE in result['strategy_ids']) == baseline, observations
        quote = 104 if strategy_id == 'TREND_PULLBACK_RECLAIM' else 102
        plan = scanner._candidate_target_plan(result, 'BUY', quote, cfg, quote_at=STAMP)
    signal = dict(ticker=ticker, company='Synthetic image fixture', action='BUY', entry=quote,
        stop_loss=plan['stop'], target_plan=plan, quote_at=STAMP, confidence=.91,
        time_horizon='days', reason='Synthetic image lifecycle proof, not a market signal', relevant_news=[])
    return signal, result


def create(ticker, strategy_id='RELATIVE_STRENGTH_LEADER', *, baseline=False):
    signal, source = candidate(ticker, strategy_id, baseline=baseline)
    with patch.object(engine, 'now_z', return_value=STAMP):
        result = engine.record_signal(signal, source, {}, {}, 'isolated-entry-image')
    assert result['status'] == 'PENDING_ENTRY', result
    return stored(ticker)


def backup(name, expected_format):
    data = recovery.export_postgres(URL)
    assert data['version'] == data['recovery_format'] == expected_format
    identity_file = ROOT / 'synthetic-age-identity'
    if not identity_file.exists():
        subprocess.run(['age-keygen', '-o', str(identity_file)], check=True, capture_output=True)
    recipient = subprocess.check_output(['age-keygen', '-y', str(identity_file)]).decode().strip()
    encrypted, sizes = recovery.encrypted_bytes(data, recipient)
    artifact = ROOT / (name + '.age')
    artifact.write_bytes(encrypted)
    assert recovery.decrypt(artifact, identity_file) == data
    (ROOT / (name + '-core.json')).write_text(json.dumps(state(), sort_keys=True))
    # Recovery's existing active-only contract excludes closed trades/history.
    # Compare restore with the exported active projection, not omitted history.
    active = state()
    for key, table in (('trades', 'scanner_trades'), ('fills', 'scanner_fills')):
        ids = {row['id'] for row in data['tables'][table]}
        active[key] = [row for row in active[key] if row['id'] in ids]
    # Ordinary pending entries are intentionally outside active-state transfer.
    # Compare the restored reservation with exported orders, never the live
    # pending+held total. Do not weaken or erase the held reservation check.
    restored_reservation = sum(row['limit_price']*row['quantity']
        for row in data['tables']['scanner_orders']
        if row['status'] in ('pending', 'recovery_uncertain') and row['purpose'] == 'entry')
    assert restored_reservation == data['hold_coverage']['entry_reserved_notional']
    active['reserved'] = [{'amount': restored_reservation}]
    (ROOT / (name + '-restored-core.json')).write_text(json.dumps(active, sort_keys=True))
    DETAILS.update(recovery_format=expected_format, encrypted_bytes=sizes['encrypted_bytes'],
                   hold_count=len(data['hold_coverage']['order_ids']), core_sha256=digest(state()))


if PHASE == 'identity_bridge':
    identity('bridge')
elif PHASE == 'identity_candidate':
    identity('candidate')
elif PHASE == 'old_seed':
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
    assert {row['strategy'] for row in rows("SELECT strategy FROM scanner_trades WHERE ticker='V1_ACTIVE'")} == {'single', 'staged'}
    assert recovery.export_postgres(URL)['version'] == 2
    (ROOT / 'old-core.json').write_text(json.dumps(state(), sort_keys=True))
    DETAILS['recovery_format'] = 2
elif PHASE == 'candidate_audit':
    identity('candidate')
    assert state() == json.loads((ROOT / 'old-core.json').read_text())
    for ticker in ('AUDIT_ACTIVE', 'AUDIT_PENDING'):
        saved = create(ticker, baseline=True)
        assert 'entry_strategy_execution' not in saved
    # Frozen detector output, not application code; used to try actual disabled
    # bridge admission. No bridge monkeypatch or capability override is used.
    signal, source = candidate('BRIDGE_MUST_BLOCK', 'RELATIVE_STRENGTH_LEADER')
    (ROOT / 'new-admission-fixture.json').write_text(json.dumps([signal, source]))
    bar('AUDIT_ACTIVE', 102)
    assert recovery.export_postgres(URL)['version'] == 7
elif PHASE == 'bridge_audit':
    identity('bridge')
    # Direct admission of an existing new-only package is blocked despiteflagsON.
    import entry_discovery
    assert entry_discovery.enabled_ids() == ()
    signal, source = json.loads((ROOT / 'new-admission-fixture.json').read_text())
    before_admission = state()
    try:
        with patch.object(engine, 'now_z', return_value=STAMP):
            engine.record_signal(signal, source, {}, {}, 'bridge-must-block')
    except ValueError as exc:
        assert str(exc) == 'new_entry_discovery_disabled', str(exc)
    else:
        raise AssertionError('bridge_must_block_new_creation_even_with_flags_on')
    assert state() == before_admission
    DETAILS['actual_new_creation_rejected_with_flags_on'] = True
    flags(False)
    before = state()
    engine.initialize_runtime()
    assert state() == before
    plan = stored('AUDIT_PENDING')['target_plan']
    from single_target_policy import validate_fill
    assert validate_fill(plan, 100.8) >= 2
    bar('AUDIT_PENDING', 100.8)
    assert order('AUDIT_PENDING')['status'] == 'filled'
    assert all(100.8 <= row['entry_price'] < 100.85 for row in
               rows("SELECT entry_price FROM scanner_trades WHERE ticker='AUDIT_PENDING'"))
    assert state()['holds'] == before['holds']
    backup('audit7', 7)
elif PHASE == 'candidate_execution':
    identity('candidate')
    for ticker in ('RS_ACTIVE', 'RS_PENDING', 'RS_HELD'):
        saved = create(ticker)
        assert abs(saved['entry_strategy_execution']['branches'][0]['support'] - 100.85) < 1e-9
    create('PULL_ACTIVE', 'TREND_PULLBACK_RECLAIM')
    bar('RS_ACTIVE', 100.8)
    assert order('RS_ACTIVE')['status'] == 'pending'
    assert stored('RS_ACTIVE')['last_strategy_entry_block']['reason'] == 'strategy_fill_below_support'
    bar('RS_ACTIVE', 102, 10)
    bar('PULL_ACTIVE', 104)
    bad = bar('RS_HELD', 100.8)
    with patch.object(engine, 'now_z', return_value='2026-10-06T14:20:00+00:00'):
        engine._pending_recovery_check('RS_HELD', [], datetime(2026, 10, 6, 14, 20, tzinfo=timezone.utc))
    assert order('RS_HELD')['status'] == 'recovery_uncertain'
    assert recovery.export_postgres(URL)['version'] == 8
    (ROOT / 'candidate-core.json').write_text(json.dumps(state(), sort_keys=True))
    DETAILS['guarded_hold'] = True
elif PHASE == 'old_runtime_unsafe':
    # Old runtime ignorance is tested on a disposable DB clone, never the
    # supported current-DB route. A successful forbidden fill proves UNSAFE.
    assert order('RS_PENDING')['status'] == 'pending'
    bar('RS_PENDING', 100.8)
    assert order('RS_PENDING')['status'] == 'filled'
    assert all(100.8 <= row['entry_price'] < 100.85 for row in
               rows("SELECT entry_price FROM scanner_trades WHERE ticker='RS_PENDING'"))
    DETAILS['rollback_support'] = 'UNSAFE_NOT_SUPPORTED'
    DETAILS['old_runtime_ignored_new_frozen_pivot'] = True
elif PHASE in ('bridge_execution', 'bridge_restart'):
    identity('bridge')
    flags(False)
    before = state()
    engine.initialize_runtime()
    assert state() == before
    if PHASE == 'bridge_execution':
        assert before == json.loads((ROOT / 'candidate-core.json').read_text())
        bar('RS_PENDING', 100.8)
        assert order('RS_PENDING')['status'] == 'pending'
        bar('RS_PENDING', 102, 10)
        assert order('RS_PENDING')['status'] == 'filled'
        target = stored('RS_ACTIVE')['target_plan']['active_target']
        bar('RS_ACTIVE', target, 15)
        assert rows("SELECT status FROM scanner_trades WHERE ticker='RS_ACTIVE'") == [{'status': 'closed'}]
        assert state()['holds'] == before['holds']
        backup('execution8', 8)
    else:
        assert before == json.loads((ROOT / 'execution8-core.json').read_text())
        with patch.object(engine, '_bar_dicts', return_value=[]):
            engine.monitor_prices()
        assert state() == before  # no expiry releases an uncertainty reservation
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
elif PHASE == 'bridge_restore':
    identity('bridge')
    flags(False)
    assert parsed.path == '/restored_entry'
    migrations.migrate()
    data = recovery.decrypt(ROOT / 'execution8.age', ROOT / 'synthetic-age-identity')
    recovery.restore(data, URL, 'synthetic-entry-image-token-longer-than-32-characters')
    engine.initialize_runtime()
    assert state() == json.loads((ROOT / 'execution8-restored-core.json').read_text())
    assert rows('SELECT count(*) n FROM scanner_telegram_outbox') == [{'n': 0}]
    before = state()
    target = stored('PULL_ACTIVE')['target_plan']['active_target']
    bar('PULL_ACTIVE', target, 15)
    assert state()['holds'] == before['holds'] and len(state()['fills']) == len(before['fills']) + 1
    after = state()
    engine.initialize_runtime()
    bar('PULL_ACTIVE', target, 15)
    assert state() == after
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    DETAILS['restore_preserved_holds'] = len(state()['holds'])
elif PHASE == 'bridge_restore_audit':
    identity('bridge')
    flags(False)
    assert parsed.path == '/restored_audit'
    migrations.migrate()
    data = recovery.decrypt(ROOT / 'audit7.age', ROOT / 'synthetic-age-identity')
    recovery.restore(data, URL, 'synthetic-audit-image-token-longer-than-32-characters')
    engine.initialize_runtime()
    assert state() == json.loads((ROOT / 'audit7-restored-core.json').read_text())
    before = state()
    target = stored('AUDIT_ACTIVE')['target_plan']['active_target']
    bar('AUDIT_ACTIVE', target, 15)
    assert state()['holds'] == before['holds'] and len(state()['fills']) == len(before['fills']) + 1
    after = state()
    engine.initialize_runtime()
    bar('AUDIT_ACTIVE', target, 15)
    assert state() == after
    DETAILS['recovery_format'] = 7
elif PHASE == 'old_reader_refused':
    for name in ('audit7', 'execution8'):
        try:
            recovery.decrypt(ROOT / (name + '.age'), ROOT / 'synthetic-age-identity')
        except ValueError as exc:
            assert str(exc) == 'not_a_recovery_snapshot', str(exc)
        else:
            raise AssertionError('old_backup_reader_must_reject_new_format')
    DETAILS['backup_formats_rejected'] = [7, 8]
elif PHASE == 'candidate_emergency':
    identity('candidate')
    import entry_emergency as emergency
    assert emergency_state() == emergency.initial()  # OFF bootstrap wrote nothing.
    create('PAUSED_RS')
    with patch.object(engine, 'now_z', return_value=STAMP):
        assert record('PAUSED_BASE')['status'] == 'PENDING_ENTRY'
    # A real retained short entry uses its own unchanged target contract.
    from test_automatic_short import plan as short_plan
    os.environ['STOCK_SCANNER_SHORT_ENABLED'] = 'true'
    p = short_plan()
    signal = dict(ticker='PAUSED_SHORT', company='Synthetic', action='SHORT', entry=100,
        stop_loss=p['stop'], target_plan=p, confidence=.91, time_horizon='days', reason='Synthetic')
    with patch.object(engine, 'now_z', return_value=STAMP):
        assert engine.record_signal(signal, {}, {}, {}, 'isolated-short')['status'] == 'PENDING_ENTRY'
    saved = {ticker: order(ticker) for ticker in ('PAUSED_RS', 'PAUSED_BASE', 'PAUSED_SHORT')}
    paused = emergency.set_paused(True, 0, now=datetime(2026, 10, 6, 14, 1, tzinfo=timezone.utc))
    before = state()
    for ticker, price in (('PAUSED_RS', 102), ('PAUSED_BASE', 100), ('PAUSED_SHORT', 100)):
        bar(ticker, price)
        assert order(ticker) == saved[ticker]
    assert state() == before
    new_signal, new_source = candidate('PAUSED_NEW', 'RELATIVE_STRENGTH_LEADER')
    try:
        with patch.object(engine, 'now_z', return_value='2026-10-06T14:12:00Z'):
            engine.record_signal(new_signal, new_source, {}, {}, 'isolated-paused-create')
    except ValueError as exc:
        assert str(exc) == 'entry_emergency_paused', str(exc)
    else:
        raise AssertionError('paused_creation_must_be_rejected')
    assert state() == before
    # Existing open position exits while ALL new/pending entries remain stopped.
    target = stored('PULL_ACTIVE')['target_plan']['active_target']
    bar('PULL_ACTIVE', target, 10)
    assert rows("SELECT status FROM scanner_trades WHERE ticker='PULL_ACTIVE'") == [{'status': 'closed'}]
    assert state()['holds'] == before['holds']
    assert emergency_state() == paused
    (ROOT / 'emergency-state.json').write_text(json.dumps(paused, sort_keys=True))
    (ROOT / 'emergency-before-bridge.json').write_text(json.dumps(state(), sort_keys=True))
    DETAILS['all_entry_routes_stopped_and_existing_tp_exited'] = True
elif PHASE == 'bridge_emergency':
    identity('bridge')
    flags(False)
    import entry_emergency as emergency
    before = state()
    assert before == json.loads((ROOT / 'emergency-before-bridge.json').read_text())
    engine.initialize_runtime()
    assert state() == before
    assert emergency_state() == json.loads((ROOT / 'emergency-state.json').read_text())
    for ticker, price in (('PAUSED_RS', 102), ('PAUSED_BASE', 100), ('PAUSED_SHORT', 100)):
        bar(ticker, price, 10)
        assert order(ticker)['status'] == 'pending'
    assert state() == before
    backup('emergency9', 9)
    resumed = emergency.set_paused(False, 1, now=datetime(2026, 10, 6, 14, 17, tzinfo=timezone.utc))
    bar('PAUSED_RS', 102, 15)  # A bar straddling resume must not execute later.
    assert order('PAUSED_RS')['status'] == 'pending'
    engine.initialize_runtime()
    bar('PAUSED_RS', 102, 20)
    assert order('PAUSED_RS')['status'] == 'filled'
    after = state()
    engine.initialize_runtime()
    bar('PAUSED_RS', 102, 20)
    assert state() == after and emergency_state() == resumed
    assert after['holds'] == before['holds']
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    DETAILS['restart_resume_no_retroactive_or_duplicate_fill'] = True
elif PHASE == 'bridge_restore_emergency':
    identity('bridge')
    flags(False)
    assert parsed.path == '/restored_emergency'
    migrations.migrate()
    data = recovery.decrypt(ROOT / 'emergency9.age', ROOT / 'synthetic-age-identity')
    assert data['version'] == data['recovery_format'] == 9
    recovery.restore(data, URL, 'synthetic-emergency-image-token-over-32-characters')
    engine.initialize_runtime()
    assert state() == json.loads((ROOT / 'emergency9-restored-core.json').read_text())
    assert emergency_state() == json.loads((ROOT / 'emergency-state.json').read_text())
    assert rows('SELECT count(*) n FROM scanner_telegram_outbox') == [{'n': 0}]
    before = state()
    # Saved snapshot omits ordinary pending orders by design; it retains holds
    # and open trades. Restored entry permission is independently still paused.
    import entry_emergency as emergency
    with database.get_db_connection() as conn:
        assert not emergency.check(conn.cursor())['allowed']
    assert state()['holds'] == before['holds']
    target = stored('RS_PENDING')['target_plan']['active_target']
    bar('RS_PENDING', target, 20)
    assert rows("SELECT status FROM scanner_trades WHERE ticker='RS_PENDING'") == [{'status': 'closed'}]
    after = state()
    assert after['holds'] == before['holds']
    engine.initialize_runtime()
    bar('RS_PENDING', target, 20)
    assert state() == after
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    DETAILS['encrypted_restore_preserved_pause_holds_and_exits'] = True
elif PHASE == 'old_reader_refused_emergency':
    try:
        recovery.decrypt(ROOT / 'emergency9.age', ROOT / 'synthetic-age-identity')
    except ValueError as exc:
        assert str(exc) == 'not_a_recovery_snapshot', str(exc)
    else:
        raise AssertionError('old_backup_reader_must_reject_emergency_format9')
    DETAILS['backup_formats_rejected'] = [9]
else:
    raise SystemExit('unsupported_test_phase')

print(json.dumps(dict(phase=PHASE, status='PASS', build_sha=os.environ.get('BUILD_SHA'), **DETAILS), sort_keys=True))
