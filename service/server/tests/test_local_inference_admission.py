"""Real admission/routing paths, synthetic clocks and providers; no model calls."""
import threading
import time
from unittest.mock import Mock

import pytest

from test_ai_routing import fixture, gateway, native, DECISION, SCHEMA
from test_final_ai_preflight import pipeline
from test_trump_truth_translation import db as translation_db, AT, item, row, approved
import ai_provider
import ai_routing as routing
import final_ai
import stock_scanner as scanner


def state(*, busy=False, available=True):
    return dict(protocol=1, model=routing.MODEL, digest=routing.DIGEST, capacity=1,
                ready=available and not busy,
                admission=dict(version=1, available=available, busy=busy))


def test_gateway_reports_busy_separately_without_changing_legacy_ready():
    g = gateway()
    engine = g.Inference()
    engine.available = True
    engine.at = time.monotonic()
    engine.http = Mock(side_effect=AssertionError('Health must not call a model'))
    engine.slot.acquire()
    try:
        h = engine.health()
        assert h['ready'] is False
        assert h['admission'] == dict(version=1, available=True, busy=True)
    finally:
        engine.slot.release()
    assert engine.health()['ready'] is True  # Cold is still admissible.
    engine.http.assert_not_called()


def test_actual_gateway_concurrent_request_does_not_queue_or_generate_twice():
    g = gateway()
    engine = g.Inference()
    engine.available = engine.loaded = True
    engine.at = time.monotonic()
    entered, release = threading.Event(), threading.Event()
    generations, replies = [], []
    def upstream(method, path, payload=None, **kwargs):
        if path == '/api/tags':
            return {'models': [dict(name=g.MODEL, digest=g.DIGEST)]}
        assert method == 'POST' and path == '/api/chat'
        generations.append(payload)
        entered.set()
        assert release.wait(3)
        return native({'ok': True})
    engine.http = Mock(side_effect=upstream)
    payload = dict(protocol=1, model=g.MODEL, digest=g.DIGEST, schema=SCHEMA,
                   messages=[dict(role='user', content='synthetic')], predict=50, request_id='synthetic')
    thread = threading.Thread(target=lambda: replies.append(engine.complete(payload)))
    thread.start()
    try:
        assert entered.wait(2)
        # The healthy in-flight request outlives a metadata refresh TTL.
        engine.at = time.monotonic() - 66
        assert engine.health()['admission'] == dict(version=1, available=True, busy=True)
        with pytest.raises(g.AdmissionBusy):
            engine.complete(payload)
        assert len(generations) == 1
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and len(replies) == 1
    assert not engine.slot.locked() and engine.health()['ready']


def test_busy_route_never_falls_back_or_sets_outage_cooldown(fixture, monkeypatch):
    relay, paid, budget, slot, ledger = fixture
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', 'false')
    relay.side_effect = None
    relay.return_value = state(busy=True)
    with pytest.raises(routing.LocalBusy):
        final_ai.review([dict(role='user', content='synthetic')], lambda v: v)
    paid.assert_not_called()
    budget.assert_not_called()
    ledger.assert_not_called()
    assert routing._until == 0


def test_wait_uses_metadata_only_and_returns_when_slot_becomes_free(fixture, monkeypatch):
    relay, paid, budget, slot, ledger = fixture
    relay.side_effect = [state(busy=True), state(busy=True), state()]
    clock = [10.0]
    monkeypatch.setattr(routing.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(routing.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert routing.wait_for_admission(deadline=12, permitted=lambda: True) is True
    assert all(call.args[:2] == ('GET', '/health') for call in relay.call_args_list)
    assert 10 < clock[0] <= 12
    assert routing._until == 0
    paid.assert_not_called()
    ledger.assert_not_called()


def test_busy_then_free_reaches_one_valid_final_review_without_paid_fallback(fixture, monkeypatch):
    relay, paid, budget, slot, ledger = fixture
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', 'false')
    health_calls = [0]
    def invoke(method, path, *a, **kw):
        if path == '/health':
            health_calls[0] += 1
            return state(busy=health_calls[0] == 1)
        return native(DECISION)
    relay.side_effect = invoke
    monkeypatch.setattr(routing.time, 'sleep', lambda _: None)
    assert routing.wait_for_admission(deadline=time.monotonic() + 2, permitted=lambda: True)
    trace = final_ai.new_trace('synthetic', 'TEST', 1)
    token = final_ai.TRACE.set(trace)
    try:
        assert final_ai.review([dict(role='user', content='synthetic')], lambda v: v) == DECISION
    finally:
        final_ai.TRACE.reset(token)
    assert len(trace['attempts']) == ledger.call_count == 1
    assert sum(c.args[0] == 'POST' for c in relay.call_args_list) == 1
    paid.assert_not_called()
    budget.assert_not_called()


@pytest.mark.parametrize('halt', ['deadline', 'session'])
def test_busy_wait_is_bounded_and_never_generates(fixture, monkeypatch, halt):
    relay, paid, budget, slot, ledger = fixture
    relay.side_effect = None
    relay.return_value = state(busy=True)
    clock = [10.0]
    monkeypatch.setattr(routing.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(routing.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(routing.LocalBusy):
        routing.wait_for_admission(deadline=11, permitted=lambda: halt != 'session' or clock[0] < 10.5)
    assert clock[0] <= 11
    assert routing._until == 0
    assert all(call.args[0] == 'GET' for call in relay.call_args_list)
    ledger.assert_not_called()
    paid.assert_not_called()


def test_explicit_enabled_fallback_still_handles_actual_outage(fixture, monkeypatch):
    relay, paid, *_ = fixture
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', 'true')
    relay.side_effect = None
    relay.return_value = state(available=False)
    assert routing.wait_for_admission(deadline=time.monotonic() + 1, permitted=lambda: True) is False
    assert routing.Route('openrouter', 'synthetic').provider == 'openrouter'
    paid.assert_not_called()  # Admission does not generate on either provider.


@pytest.mark.parametrize('change', [
    {'admission': {'version': 1, 'available': False, 'busy': True}},
    {'admission': {'version': True, 'available': True, 'busy': True}},
    {'admission': {'version': 1, 'available': True, 'busy': 1}},
    {'admission': {'version': 1, 'available': True, 'busy': True, 'extra': 1}},
    {'digest': '0' * 64}, {'model': 'other'}, {'protocol': 2}, {'capacity': True},
])
def test_invalid_or_unavailable_state_cannot_become_busy_wait(fixture, change):
    relay, *_ = fixture
    relay.side_effect = None
    relay.return_value = {**state(busy=True), **change}
    # The explicit fallback policy is separate from a typed busy deferral.
    import os
    from unittest.mock import patch
    with patch.dict(os.environ, {'AI_OPENROUTER_FALLBACK_ENABLED': 'false'}):
        with pytest.raises(routing.LocalUnavailable):
            routing.wait_for_admission(deadline=time.monotonic() + 2, permitted=lambda: True)
    assert relay.call_count == 1


@pytest.mark.parametrize('caller', ['shared', 'final'])
def test_completion_admission_race_is_not_a_model_attempt(fixture, monkeypatch, caller):
    relay, paid, budget, slot, ledger = fixture
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', 'false')
    relay.side_effect = lambda method, path, *a, **kw: (
        state() if method == 'GET' else (_ for _ in ()).throw(routing.LocalBusy('local_inference_busy')))
    trace = final_ai.new_trace('synthetic', 'TEST', 1)
    token = final_ai.TRACE.set(trace)
    try:
        with pytest.raises(routing.LocalBusy):
            if caller == 'shared':
                ai_provider.json_completion('synthetic', {}, schema=SCHEMA)
            else:
                final_ai.review([dict(role='user', content='synthetic')], lambda v: v)
    finally:
        final_ai.TRACE.reset(token)
    assert trace['attempts'] == [] and trace['ai_started'] is False
    assert routing._until == 0
    assert sum(c.args[0] == 'POST' for c in relay.call_args_list) == 1
    paid.assert_not_called()
    ledger.assert_not_called()


def test_scanner_after_wait_rechecks_emergency_before_obtaining_fresh_inputs(pipeline, monkeypatch):
    candidates, quote, ai, events, _ = pipeline
    ordering = []
    import entry_emergency
    check = Mock(return_value=dict(valid=True, paused=False, reason=None))
    monkeypatch.setattr(entry_emergency, 'status', check)
    def wait(**kwargs):
        ordering.append('wait')
        check.return_value = dict(valid=True, paused=True, reason='entry_emergency_paused')
        return True
    monkeypatch.setattr(routing, 'wait_for_admission', wait)
    quote.side_effect = lambda *a: ordering.append('quote') or (100, '2026-09-25T15:00:00Z')
    result = scanner.run_scan()
    assert ordering == ['quote', 'wait']
    assert ai.call_count == 0 and quote.call_count == 1
    assert result['signals_published'] == 0
    assert any(r['reason'] == 'pre_entry_emergency_paused' for r in result['rejected'])


def test_scanner_busy_deadline_defers_without_spending_candidate_quota(pipeline, monkeypatch):
    _, quote, ai, events, _ = pipeline
    monkeypatch.setattr(routing, 'wait_for_admission', Mock(side_effect=routing.LocalBusy('local_inference_busy')))
    result = scanner.run_scan()
    assert quote.call_count == 1  # Initial structural precheck, never reused.
    ai.assert_not_called()
    assert len(events) == 1
    assert events[0]['attempts'] == [] and events[0]['ai_started'] is False
    assert result['signals_published'] == 0
    assert result['rejected'] == [dict(ticker='T1', reason='pre_local_inference_busy')]


def test_direct_translation_busy_race_does_not_record_model_usage(monkeypatch):
    import ai_operations
    import trump_truth_translation as translation
    monkeypatch.setenv('AI_TRADER_CLOUD', 'false')
    monkeypatch.setattr(routing, 'enabled', lambda: True)
    monkeypatch.setattr(routing, 'ready', lambda: True)
    monkeypatch.setattr(routing, 'local_completion', Mock(side_effect=routing.LocalBusy('local_inference_busy')))
    ledger = Mock()
    monkeypatch.setattr(ai_operations, 'record', ledger)
    with pytest.raises(routing.LocalBusy):
        translation.local_json('synthetic', {'source_excerpt': 'Synthetic'}, translation.SCHEMA)
    ledger.assert_not_called()


def test_first_translation_stage_busy_creates_no_cache_attempt(translation_db):
    import trump_truth_posts as posts
    import trump_truth_translation as translation
    posts.ingest([item()], AT)
    completion = Mock(side_effect=routing.LocalBusy('local_inference_busy'))
    assert translation.prepare(at=AT, completion=completion) == {'prepared': 0, 'deferred': 1}
    r = row(translation_db)
    assert r['status'] == translation.PENDING
    assert r['last_error'] == 'trump_hebrew_capacity_deferred'
    with translation_db.get_db_connection() as c:
        assert c.execute('SELECT 1 FROM scanner_settings WHERE key IN (?,?)',
            (translation.cache_key(r), translation.diagnostic_key(r))).fetchall() == []
        assert c.execute('SELECT count(*) FROM scanner_fills').fetchone()[0] == 0
    assert completion.call_count == 1


def test_busy_restores_only_unspent_new_attempt_and_preserves_previous_failure(translation_db):
    from datetime import timedelta
    import trump_truth_posts as posts
    import trump_truth_translation as translation
    posts.ingest([item()], AT)
    translation.prepare(at=AT, completion=Mock(side_effect=ValueError('synthetic')))
    r = row(translation_db)
    def cache():
        with translation_db.get_db_connection() as c:
            return [dict(r) for r in c.execute('SELECT key,value_json,updated_at FROM scanner_settings WHERE key IN (?,?) ORDER BY key',
                (translation.cache_key(r), translation.diagnostic_key(r)))]
    before = cache()
    assert translation.prepare(at=AT + timedelta(seconds=61),
        completion=Mock(side_effect=routing.LocalBusy('local_inference_busy'))) == {'prepared': 0, 'deferred': 1}
    assert cache() == before
    assert translation.prepare(at=AT + timedelta(seconds=122), completion=approved) == {'prepared': 1, 'deferred': 0}


def test_review_stage_busy_preserves_real_prior_work_attempt(translation_db):
    import json
    import trump_truth_posts as posts
    import trump_truth_translation as translation
    posts.ingest([item()], AT)
    completion = Mock(side_effect=[{'text_he': 'לא נעלה את המכסים ב־5%.'},
                                   routing.LocalBusy('local_inference_busy')])
    assert translation.prepare(at=AT, completion=completion) == {'prepared': 0, 'deferred': 1}
    r = row(translation_db)
    with translation_db.get_db_connection() as c:
        cache = json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',
                                     (translation.cache_key(r),)).fetchone()[0])
        diagnostic = json.loads(c.execute('SELECT value_json FROM scanner_settings WHERE key=?',
                                          (translation.diagnostic_key(r),)).fetchone()[0])
    assert cache['attempts'] == 1 and cache['status'] == 'working'
    assert diagnostic['category'] == 'admission_busy'
    assert completion.call_count == 2
