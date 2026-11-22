"""Independent adversarial checks; synthetic providers only, no model execution."""
import json
import copy
import hashlib
import threading
import time
from unittest.mock import Mock

import pytest
import requests

import ai_routing as routing
import stock_scanner as scanner
from test_ai_routing import fixture, gateway
from test_final_ai_preflight import pipeline


def health(*, available=True, busy=False):
    return dict(protocol=1, model=routing.MODEL, digest=routing.DIGEST,
                capacity=1, ready=available and not busy,
                admission=dict(version=1, available=available, busy=busy))


def test_actual_relay_accepts_only_exact_busy_contract(monkeypatch):
    response = Mock(status=429,
                    read=lambda _: b'{"reason":"local_inference_busy"}')
    connection = Mock(sock=None)
    connection.getresponse.return_value = response
    monkeypatch.setattr(routing, 'UnixHTTP', lambda *a, **kw: connection)
    with pytest.raises(routing.LocalBusy):
        routing.relay('POST', '/completion', {'synthetic': True})
    connection.close.assert_called_once()
    assert connection.request.call_count == 1


@pytest.mark.parametrize('status,body', [
    (503, {'reason': 'local_inference_busy'}),
    (429, {'reason': 'other'}),
    (429, {'reason': 'local_inference_busy', 'extra': 'untrusted'}),
    (429, {'reason': ['local_inference_busy']}),
])
def test_generic_http_failures_cannot_masquerade_as_busy(monkeypatch, status, body):
    response = Mock(status=status, read=lambda _: json.dumps(body).encode())
    connection = Mock(sock=None)
    connection.getresponse.return_value = response
    monkeypatch.setattr(routing, 'UnixHTTP', lambda *a, **kw: connection)
    with pytest.raises(requests.RequestException):
        routing.relay('POST', '/completion', {'synthetic': True})
    connection.close.assert_called_once()


@pytest.mark.parametrize('fallback', ['true', 'false'])
def test_busy_is_not_paid_fallback_permission(fixture, monkeypatch, fallback):
    relay, paid, budget, _, ledger = fixture
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', fallback)
    relay.side_effect = None
    relay.return_value = health(busy=True)
    with pytest.raises(routing.LocalBusy):
        routing.Route('openrouter', 'synthetic-model')
    assert routing._until == 0
    paid.assert_not_called()
    budget.assert_not_called()
    ledger.assert_not_called()


def test_expired_gateway_metadata_does_not_claim_waitable_capacity():
    module = gateway()
    engine = module.Inference()
    engine.available = True
    engine.at = time.monotonic() - 66
    engine.http = Mock(side_effect=AssertionError('Read-only health cannot run inference'))
    with engine.slot:
        state = engine.health()
    assert state['ready'] is False
    assert state['admission'] == dict(version=1, available=False, busy=True)
    engine.http.assert_not_called()


def test_actual_gateway_keeps_one_generation_and_busy_refresh_never_loads():
    module = gateway()
    engine = module.Inference()
    engine.available, engine.loaded = True, True
    engine.at = time.monotonic()
    entered, release = threading.Event(), threading.Event()
    calls, outcomes, errors = [], [], []

    def http(method, path, payload=None, **kwargs):
        calls.append((method, path))
        if method == 'GET' and path == '/api/tags':
            return {'models': [{'name': module.MODEL, 'digest': module.DIGEST}]}
        assert (method, path) == ('POST', '/api/chat')
        entered.set()
        assert release.wait(2), 'synthetic native worker was not released'
        return dict(model=module.MODEL, done=True, done_reason='stop',
                    message={'content': '{"ok":true}'})

    engine.http = http
    payload = dict(protocol=1, model=module.MODEL, digest=module.DIGEST,
                   messages=[dict(role='user', content='synthetic')], schema=None,
                   predict=50, request_id='synthetic-one')

    def first():
        try:
            outcomes.append(engine.complete(payload))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=first, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        before = list(calls)
        assert engine.health()['admission'] == dict(version=1, available=True, busy=True)
        engine.refresh()
        assert calls == before  # No periodic preload or health model traffic.
        with pytest.raises(module.AdmissionBusy):
            engine.complete(dict(payload, request_id='synthetic-two'))
        assert calls.count(('POST', '/api/chat')) == 1
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and not errors
    assert len(outcomes) == 1 and engine.health()['ready'] is True
    assert calls.count(('POST', '/api/chat')) == 1


def test_busy_wait_then_market_close_cannot_use_stale_session(pipeline, monkeypatch):
    _, quote, ai, _, session = pipeline
    open_now = [True]
    monkeypatch.setattr(scanner, 'regular_session_open', lambda: open_now[0])

    def wait(**kwargs):
        open_now[0] = False
        return True

    monkeypatch.setattr(routing, 'wait_for_admission', wait)
    result = scanner.run_scan()
    assert quote.call_count == 1  # Structural precheck precedes capacity waiting.
    ai.assert_not_called()
    session.request.assert_not_called()
    assert result['signals_published'] == 0
    assert any('waiting_regular_session' in row['reason'] for row in result['rejected'])


def test_busy_wait_then_fresh_quote_is_rechecked_against_real_target_policy(pipeline, monkeypatch):
    _, quote, ai, _, session = pipeline
    ordering = []
    monkeypatch.setattr(routing, 'wait_for_admission',
                        lambda **kw: ordering.append('wait') or True)
    def current_quote(*args):
        ordering.append('quote')
        # Valid before the wait, newly invalid on the post-wait witness.
        return (100 if ordering.count('quote') % 2 else 97, '2026-09-25T15:00:00Z')
    quote.side_effect = current_quote
    result = scanner.run_scan()
    assert ordering and ordering[0:3] == ['quote', 'wait', 'quote']
    ai.assert_not_called()
    session.request.assert_not_called()
    assert result['signals_published'] == 0
    assert result['rejected']


def _opening_case():
    trade = dict(id=19, agent_id=4, is_shadow=0, legacy_position_id=None,
                 side='long', entry_price=20., original_quantity=3., remaining_quantity=2.,
                 fees=.4, realized_pnl=3.)
    fills = {19: [dict(trade_id=19, fill_type='entry', price=20., quantity=3., fee=.2, gross_pnl=0.),
                  dict(trade_id=19, fill_type='tp', price=23., quantity=1., fee=.2, gross_pnl=3.)]}
    account = dict(agent_id=4, initial_cash=100., cash=70.6, fees_paid=1.4, realized_pnl=11.)
    original = dict(version=1, primary_agent_id=4, tables={
        'scanner_accounts': [copy.deepcopy(account)], 'scanner_trades': [copy.deepcopy(trade)],
        'scanner_fills': copy.deepcopy(fills[19])})
    original['snapshot_id'] = hashlib.sha256(json.dumps(original, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    baseline = dict(snapshot_id=original['snapshot_id'], cash_adjustment=8.,
                    historical_performance_not_imported=True)
    return [account], [trade], fills, baseline, original


def test_independent_original_opening_proof_closes_only_retained_accounting():
    from accounting_audit import reconcile
    accounts, trades, fills, baseline, snapshot = _opening_case()
    result = reconcile(accounts, trades, fills, baseline=baseline, opening_snapshot=snapshot)
    assert result['status'] == 'PASS'
    assert result['historical_performance'] == 'NOT_ASSESSED'
    assert result['natural_trading_e2e'] == 'NOT_VERIFIED'
    assert all(result['accounts'][0][key]['status'] == 'PASS' for key in ('cash', 'fees', 'realized'))
    assert '70.6' not in json.dumps(result) and '11.0' not in json.dumps(result)


def test_replacing_original_with_new_self_consistent_snapshot_is_not_import_proof():
    from accounting_audit import reconcile
    accounts, trades, fills, baseline, snapshot = _opening_case()
    snapshot.pop('snapshot_id')
    snapshot['tables']['scanner_accounts'][0]['fees_paid'] += 2
    snapshot['snapshot_id'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    result = reconcile(accounts, trades, fills, baseline=baseline, opening_snapshot=snapshot)
    assert result['status'] == 'NOT_VERIFIED'
    assert result['accounts'][0]['fees']['reason'] == 'OPENING_SNAPSHOT_ID_MISMATCH'


def test_no_original_snapshot_cannot_rebase_current_totals_into_pass():
    from accounting_audit import reconcile
    accounts, trades, fills, baseline, _ = _opening_case()
    baseline.update(opening_adjustments_version=1, opening_adjustments_source='import_snapshot',
                    opening_adjustments_snapshot_id=baseline['snapshot_id'],
                    fees_paid_adjustment=1., realized_pnl_adjustment=8.)
    result = reconcile(accounts, trades, fills, baseline=baseline)
    assert result['status'] == 'NOT_VERIFIED'
    assert result['accounts'][0]['fees']['reason'] == 'OPENING_HISTORY_GAP'


def test_real_current_aggregate_mutation_fails_with_exact_original_opening():
    from accounting_audit import reconcile
    accounts, trades, fills, baseline, original = _opening_case()
    accounts[0]['realized_pnl'] += 4
    result = reconcile(accounts, trades, fills, baseline=baseline, opening_snapshot=original)
    assert result['status'] == 'FAIL'
    assert result['accounts'][0]['realized']['status'] == 'FAIL'
    assert result['native_fills']['status'] == 'PASS'


def test_payload_deduplication_requires_identical_json_types_not_python_equality():
    from review_payload import compact, expand
    row = dict(title='Synthetic', publisher='Issuer', published_at='2026-11-20', relevance=1)
    original = dict(candidate={'news': [dict(row)]}, recent_news=[dict(row, relevance=True)])
    projected, moves = compact(original)
    assert moves == []  # JSON true and JSON number1 are different source evidence.
    assert json.dumps(expand(projected, moves), sort_keys=True) == json.dumps(original, sort_keys=True)


def test_payload_conservation_keeps_confirmation_times_and_nested_source_metadata():
    from review_payload import compact, expand
    row = dict(title='חדשות סינתטיות', publisher='Issuer', published_at='2026-11-20', relevance=.8,
               source={'details': ['fact1', {'value': None, 'available_at': '2026-11-20T14:00:00Z'}]})
    fields = ('title', 'publisher', 'published_at', 'relevance')
    plan_zone = dict(low=90., high=91., pivots=[dict(price=90.5, confirmed_at='2026-11-19T21:00:00Z')])
    original = dict(candidate={'news': [row], 'price_zones': [dict(low=90., high=91., pivots=[dict(price=90.5)])]},
                    recent_news=[{key: row[key] for key in fields}],
                    validated_target_plan={'zones': [plan_zone]})
    untouched = copy.deepcopy(original)
    projected, moves = compact(original)
    assert json.dumps(expand(projected, moves), sort_keys=True) == json.dumps(original, sort_keys=True)
    assert projected['recent_news'][0]['source'] == row['source']
    assert projected['validated_target_plan']['zones'][0]['pivots'][0]['confirmed_at'] == '2026-11-19T21:00:00Z'
    assert original == untouched


@pytest.mark.parametrize('halt', ['session', 'emergency'])
def test_post_wait_news_lookup_cannot_spend_ai_after_session_closes(pipeline, monkeypatch, halt):
    _, quote, ai, _, session = pipeline
    import entry_emergency
    open_now = [True]
    emergency = [dict(valid=True, paused=False, reason=None)]
    monkeypatch.setattr(scanner, 'regular_session_open', lambda: open_now[0])
    monkeypatch.setattr(entry_emergency, 'status', lambda **kw: emergency[0])
    original_enrich = scanner.enrich_and_rank_candidates
    calls = [0]

    def enrich(*args, **kwargs):
        calls[0] += 1
        result = original_enrich(*args, **kwargs)
        if calls[0] > 1:
            if halt == 'session':
                open_now[0] = False
            else:
                emergency[0] = dict(valid=True, paused=True, reason='entry_emergency_paused')
        return result

    monkeypatch.setattr(scanner, 'enrich_and_rank_candidates', enrich)
    monkeypatch.setattr(routing, 'wait_for_admission', lambda **kw: True)
    result = scanner.run_scan()
    assert calls[0] >= 2
    ai.assert_not_called()
    session.request.assert_not_called()
    assert result['signals_published'] == 0
