"""Synthetic price-route news policy; providers/AI/Telegram never live."""
import copy
import json
import socket
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from test_signal_inputs import db, clock
from test_signal_admission_chain import prepare, rows
from test_entry_strategy_execution import package_for
from test_single_target_v2 import zone
import database
import stock_scanner as scanner
import scanner_engine as engine
import entry_discovery
import price_news_policy as policy

PRICE_IDS = sorted(policy.ROUTES)
REAL_AI_REVIEW = scanner.ai_review
REAL_NEWS_FETCH = scanner.fetch_recent_news


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('price news tests prohibit external IO')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)


def setup_price(monkeypatch, clock, sid='RELATIVE_STRENGTH_LEADER'):
    candidate, review, session = prepare(monkeypatch, clock)
    monkeypatch.setenv(policy.FLAG, 'true')
    for key, flag in entry_discovery.FLAGS.items():
        monkeypatch.setenv(flag, 'true' if key in policy.ROUTES else 'false')
    package = package_for(sid)
    price = package['detections'][0]['entry_reference']['price']
    clock.instant = datetime(2026, 10, 6, 14, 0, 37, tzinfo=timezone.utc)
    candidate.update(entry=price, entry_discovery=package, strategy_ids=package['strategy_ids'],
        price_zones=[zone(price-2, price-1.6), zone(price+4.65, price+5)])
    monkeypatch.setattr(scanner, 'current_intraday_quote', lambda *a:(price, clock.instant.isoformat()))
    monkeypatch.setattr('entry_strategy_inputs.load_context', lambda *a, **kw:{})
    def discovery(*a, **kw):
        ids = candidate.get('entry_discovery', {}).get('strategy_ids', ['BASELINE'])
        obs = dict(ticker='TEST', baseline_detected='BASELINE' in ids, common_reasons=[],
            candidate_strategy_ids=ids, strategy_results={r['strategy_id']:r for r in
                candidate.get('entry_discovery', {}).get('detections', []) if r['strategy_id'] != 'BASELINE'})
        return [copy.deepcopy(candidate)], [obs]
    monkeypatch.setattr(entry_discovery, 'discover_candidates', discovery)
    monkeypatch.setattr('signal_news.existing_news', lambda candidates,*a,**kw:{r['ticker']:[] for r in candidates})
    review.return_value.update(news_sentiment=0, news_relevance=0)
    return candidate, review, session, price


def enrich(candidate):
    return scanner.enrich_and_rank_candidates([candidate], {}, scanner.settings())


@pytest.mark.parametrize('sid', PRICE_IDS)
def test_each_price_route_can_reach_real_pending_then_fill_and_exit_without_article(db, clock, monkeypatch, sid):
    candidate, review, session, price = setup_price(monkeypatch, clock, sid)
    result = scanner.run_scan()
    assert result['signals_published'] == 1 and review.call_count == 1
    assert result['ai_reviews'][0]['news_sentiment'] is None
    assert result['ai_reviews'][0]['news_relevance'] is None
    assert result['ai_reviews'][0]['news_context']['availability']=='NO_ELIGIBLE_STORIES'
    submitted = review.call_args.args[0]
    assert not submitted['news'] and submitted['news_context']['availability'] == 'NO_ELIGIBLE_STORIES'
    assert submitted['deterministic_news_sentiment'] is None
    assert submitted['deterministic_news_relevance'] is None
    assert rows('SELECT status FROM scanner_orders') == [{'status':'pending'}]
    assert not rows('SELECT id FROM scanner_trades')
    saved = rows('SELECT confidence_basis,technical_json FROM scanner_signals')[0]
    basis = json.loads(saved['confidence_basis'])
    assert basis['news_sentiment'] is None and basis['news_relevance'] is None
    assert basis['news_evidence_status'] == 'NOT_MEASURED_NO_ELIGIBLE_STORIES'
    assert json.loads(saved['technical_json'])['news_context']['strategy_ids'] == [sid]
    frozen = rows('SELECT plan_json FROM scanner_orders')[0]['plan_json']
    # Rollout OFF/restart never changes management of an already admitted order.
    monkeypatch.setenv(policy.FLAG, 'false')
    engine.initialize_runtime()
    clock.instant += timedelta(minutes=10)
    entry = dict(at='2026-10-06T14:05:00Z', open=price, high=price+.2, low=price-.1, close=price)
    engine.process_bar('TEST', entry)
    assert rows('SELECT status FROM scanner_orders') == [{'status':'filled'}]
    assert len(rows('SELECT id FROM scanner_trades WHERE is_shadow=0')) == 1
    assert rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'] == frozen
    clock.instant += timedelta(minutes=5)
    target = rows('SELECT tp1 FROM scanner_trades WHERE is_shadow=0')[0]['tp1']
    exit_bar = dict(at='2026-10-06T14:10:00Z', open=target, high=target+.5, low=target-.1, close=target)
    engine.process_bar('TEST', exit_bar)
    engine.initialize_runtime()
    engine.process_bar('TEST', entry); engine.process_bar('TEST', exit_bar)
    assert rows('SELECT status FROM scanner_trades WHERE is_shadow=0') == [{'status':'closed'}]
    assert len(rows('SELECT id FROM scanner_fills')) == 2
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
    assert session.request.call_count == 1  # Mocked strategy projection, not a broker.


@pytest.mark.parametrize('kind', ['flag_off','baseline','pead','short','disabled_route'])
def test_no_exception_for_unchanged_routes_or_disabled_policy(db, clock, monkeypatch, kind):
    c, review, _, _ = setup_price(monkeypatch, clock)
    if kind == 'flag_off':monkeypatch.setenv(policy.FLAG, 'false')
    if kind == 'baseline':c.pop('entry_discovery');c.pop('strategy_ids')
    if kind == 'pead':c['entry_discovery'] = package_for('PEAD')
    if kind == 'short':c['technical_direction'] = 'SELL'
    if kind == 'disabled_route':monkeypatch.setenv(entry_discovery.FLAGS['RELATIVE_STRENGTH_LEADER'], 'false')
    ranked, blocked = enrich(c)
    assert not ranked and blocked[0]['reason'] == 'insufficient_current_news'
    review.assert_not_called()


@pytest.mark.parametrize('failure', ['yahoo','canonical','both','invalid_yahoo'])
def test_unavailable_sources_are_not_successful_empty_evidence(db, clock, monkeypatch, failure):
    c, review, _, _ = setup_price(monkeypatch, clock)
    error = RuntimeError('private error must not enter policy metadata')
    if failure in ('yahoo','both'):monkeypatch.setattr(scanner,'fetch_recent_news',Mock(side_effect=error))
    if failure in ('canonical','both'):monkeypatch.setattr('signal_news.existing_news',Mock(side_effect=error))
    if failure == 'invalid_yahoo':monkeypatch.setattr(scanner,'fetch_recent_news',Mock(return_value={'unexpected':'shape'}))
    ranked, blocked = enrich(c)
    assert not ranked and blocked[0]['reason'] in {
        'news_provider_unavailable_fail_closed','news_evidence_unavailable_fail_closed'}
    assert 'private' not in json.dumps(blocked)
    review.assert_not_called()


@pytest.mark.parametrize('hours', [-1, 100])
def test_future_and_stale_articles_do_not_become_positive_context(db, clock, monkeypatch, hours):
    c, _, _, _ = setup_price(monkeypatch, clock)
    article = dict(title='Synthetic headline', relevance=.9, publisher='Synthetic',
                   published_at=(clock.instant-timedelta(hours=hours)).isoformat())
    monkeypatch.setattr(scanner, 'fetch_recent_news', Mock(return_value=[article]))
    ranked, blocked = enrich(c)
    assert not blocked and not ranked[0]['news']
    assert ranked[0]['news_context']['availability'] == 'NO_ELIGIBLE_STORIES'


def test_current_evidence_substitutes_for_one_failed_lookup(db, clock, monkeypatch):
    c, _, _, _ = setup_price(monkeypatch, clock)
    article = dict(title='Synthetic adverse earnings update',relevance=.95,publisher='Synthetic',
                   published_at=(clock.instant-timedelta(minutes=1)).isoformat())
    monkeypatch.setattr(scanner,'fetch_recent_news',Mock(side_effect=RuntimeError('synthetic outage')))
    monkeypatch.setattr('signal_news.existing_news',lambda *a,**kw:{'TEST':[article]})
    ranked, blocked = enrich(c)
    assert not blocked and ranked[0]['news'][0]['title'] == article['title']
    assert ranked[0]['news_context']['yahoo_lookup'] == 'UNAVAILABLE'
    assert ranked[0]['news_context']['availability'] == 'AVAILABLE'


@pytest.mark.parametrize('gate', ['hold','confidence','negative','quote','session','rr','trigger','emergency'])
def test_optional_article_never_bypasses_common_gates(db, clock, monkeypatch, gate):
    c, review, _, price = setup_price(monkeypatch, clock)
    if gate == 'hold':review.return_value['action'] = 'HOLD'
    if gate == 'confidence':review.return_value['confidence'] = .79
    if gate == 'negative':
        article=dict(title='Synthetic adverse facts',relevance=.9,publisher='Synthetic',published_at=clock.instant.isoformat())
        monkeypatch.setattr(scanner,'fetch_recent_news',Mock(return_value=[article]))
        review.return_value.update(news_sentiment=-.5,news_relevance=.9)
    if gate == 'quote':monkeypatch.setattr(scanner,'current_intraday_quote',lambda *a:None)
    if gate == 'session':monkeypatch.setattr(scanner,'regular_session_open',lambda:False)
    if gate == 'rr':c['price_zones'] = [zone(price-2,price-1.6),zone(price+1,price+1.4)]
    if gate == 'trigger':monkeypatch.setattr(scanner,'current_intraday_quote',lambda *a:(99,clock.instant.isoformat()))
    if gate == 'emergency':
        import entry_emergency
        engine.initialize_runtime()
        entry_emergency.set_paused(True, 0, now=clock.instant)
    result = scanner.run_scan()
    assert result['signals_published'] == 0 and result['rejected']
    assert not rows('SELECT id FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_trades')
    if gate in {'quote','session','rr','trigger','emergency'}:review.assert_not_called()
    if gate == 'negative':assert result['rejected'][0]['reason'] == 'news_sentiment_conflict'


def test_mixed_baseline_cannot_lend_its_unconditional_trigger_to_exception(db, clock, monkeypatch):
    c, _, _, price = setup_price(monkeypatch, clock)
    record = dict(strategy_id='BASELINE',version='existing_trend_momentum_v1',state='DETECTED',
        direction='BUY',score=1,source_times=dict(decision_at=clock.instant.isoformat(),
        source_observed_at=clock.instant.isoformat()),sourcehash='b'*64,trigger={'kind':'existing_trend_momentum'})
    c['entry_discovery'] = entry_discovery.attribution([record,*c['entry_discovery']['detections']],clock.instant)
    ranked, blocked = enrich(c)
    assert not blocked
    row = ranked[0];cfg=scanner.settings()
    assert policy.validate(row,cfg,price,clock.instant,clock.instant)
    with pytest.raises(ValueError,match='price_news_policy_no_valid_price_trigger'):
        policy.validate(row,cfg,99,clock.instant,clock.instant)


def test_prompt_and_real_validator_treat_no_article_as_unknown_not_neutral(db, clock, monkeypatch):
    c, _, _, price = setup_price(monkeypatch, clock)
    ranked, _ = enrich(c)
    c = dict(ranked[0],entry=price,quote_at=clock.instant.isoformat(),
             validated_target_plan={'entry':price})
    captures=[]
    def transport(messages, validator):
        captures.append(messages)
        value=dict(action='BUY',confidence=.91,news_sentiment=0,news_relevance=0,
            time_horizon='1-4 weeks',reason='Synthetic price setup supports review.',
            entry_price_relation='equal',entry_price_concern='none')
        for key in ('news_sentiment','news_relevance'):
            with pytest.raises(ValueError,match='invented_news_scores'):
                validator(dict(value,**{key:.8}))
        return validator(value)
    monkeypatch.setattr(scanner.final_ai,'review',transport)
    decision=REAL_AI_REVIEW(c,[],{})
    prompt=captures[0][0]['content'];payload=json.loads(captures[0][1]['content'])
    assert 'article is NOT required' in prompt and 'NOT_MEASURED' in prompt
    assert 'Use HOLD unless technical evidence, relevant recent news' not in prompt
    assert not payload['recent_news']
    assert decision['action']=='BUY' and decision['entry_rationale']['status']=='VERIFIED'
    with pytest.raises(ValueError,match='evidence_mismatch'):
        REAL_AI_REVIEW(c,[{'title':'fabricated'}],{})


def test_baseline_prompt_and_relevance_veto_unchanged(db, clock, monkeypatch):
    c, _, _, price=setup_price(monkeypatch,clock)
    c.pop('entry_discovery');c.pop('strategy_ids')
    transport=Mock(return_value={})
    monkeypatch.setattr(scanner.final_ai,'review',transport)
    REAL_AI_REVIEW(dict(c,entry=price,quote_at=clock.instant.isoformat()),[],{})
    assert 'Use HOLD unless technical evidence, relevant recent news' in transport.call_args.args[0][0]['content']
    decision=dict(action='BUY',confidence=.9,news_relevance=0)
    assert policy.decision_failures(decision,scanner.settings()) == ['ai_news_relevance_below_threshold']
    assert not policy.decision_failures(decision,scanner.settings(),price_context=True)
    assert policy.decision_failures(dict(decision,action='HOLD'),scanner.settings(),price_context=True)==['ai_hold']


def test_mixed_detection_freezes_price_only_execution_then_bridge_restart_and_stop(db, clock, monkeypatch):
    c, _, _, price=setup_price(monkeypatch,clock)
    c['price_zones']=[zone(99,99.2),zone(110,110.4)]
    original=c['entry_discovery']
    baseline=dict(strategy_id='BASELINE',version='existing_trend_momentum_v1',state='DETECTED',
        direction='BUY',score=1,source_times=dict(decision_at=clock.instant.isoformat(),
        source_observed_at=clock.instant.isoformat()),sourcehash='b'*64,trigger={'kind':'existing_trend_momentum'})
    c['entry_discovery']=entry_discovery.attribution([baseline,*original['detections']],clock.instant)
    c['strategy_ids']=c['entry_discovery']['strategy_ids']
    observed=copy.deepcopy(c['entry_discovery'])
    assert scanner.run_scan()['signals_published']==1
    tech=json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
    order=json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    assert tech['observed_entry_discovery']==observed
    assert tech['news_context']['observed_strategy_ids']==['BASELINE','RELATIVE_STRENGTH_LEADER']
    assert tech['entry_discovery']['strategy_ids']==['RELATIVE_STRENGTH_LEADER']
    assert order['entry_discovery']==tech['entry_discovery']
    assert order['entry_strategy_execution']['version']=='independent_entry_execution_v1'
    assert order['entry_strategy_execution']['admitted_ids']==['RELATIVE_STRENGTH_LEADER']
    clock.instant+=timedelta(minutes=10)
    engine.process_bar('TEST',dict(at='2026-10-06T14:05:00Z',open=100.8,high=101,low=100.7,close=100.9))
    assert rows('SELECT status FROM scanner_orders')==[{'status':'pending'}], rows('SELECT plan_json FROM scanner_orders')
    assert not rows('SELECT id FROM scanner_fills')
    saved=json.loads(rows('SELECT plan_json FROM scanner_orders')[0]['plan_json'])
    assert saved['last_strategy_entry_block']['reason']=='strategy_fill_below_support'
    assert saved['entry_strategy_execution']==order['entry_strategy_execution']
    monkeypatch.setenv(policy.FLAG,'false')
    for flag in entry_discovery.FLAGS.values():monkeypatch.setenv(flag,'false')
    monkeypatch.setattr('entry_discovery_capabilities.BUILD_ROLE','bridge')
    engine.initialize_runtime()
    clock.instant+=timedelta(minutes=5)
    good=dict(at='2026-10-06T14:10:00Z',open=101.1,high=101.5,low=101,close=101.3)
    engine.process_bar('TEST',good)
    assert rows('SELECT status FROM scanner_orders')==[{'status':'filled'}]
    clock.instant+=timedelta(minutes=5)
    stop=dict(at='2026-10-06T14:15:00Z',open=99,high=100,low=98.5,close=99)
    engine.process_bar('TEST',stop)
    engine.initialize_runtime();engine.process_bar('TEST',good);engine.process_bar('TEST',stop)
    assert rows('SELECT status FROM scanner_trades WHERE is_shadow=0')==[{'status':'closed'}]
    assert len(rows('SELECT id FROM scanner_fills'))==2
    assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']


def test_new_context_pending_pause_restart_resume_does_not_backfill_paused_bar(db, clock, monkeypatch):
    _, _, _, price=setup_price(monkeypatch,clock)
    assert scanner.run_scan()['signals_published']==1
    import entry_emergency
    entry_emergency.set_paused(True,0,now=datetime(2026,10,6,14,1,tzinfo=timezone.utc))
    clock.instant=datetime(2026,10,6,14,10,tzinfo=timezone.utc)
    bar=dict(at='2026-10-06T14:05:00Z',open=price,high=price+.2,low=price-.1,close=price)
    engine.process_bar('TEST',bar)
    assert not rows('SELECT id FROM scanner_fills')
    engine.initialize_runtime()
    entry_emergency.set_paused(False,1,now=datetime(2026,10,6,14,12,tzinfo=timezone.utc))
    clock.instant=datetime(2026,10,6,14,15,tzinfo=timezone.utc)
    engine.process_bar('TEST',bar)
    assert not rows('SELECT id FROM scanner_fills')
    clock.instant=datetime(2026,10,6,14,20,tzinfo=timezone.utc)
    engine.process_bar('TEST',dict(bar,at='2026-10-06T14:15:00Z'))
    assert len(rows('SELECT id FROM scanner_fills'))==1


def test_empty_news_cannot_overcome_cash_gate(db, clock, monkeypatch):
    setup_price(monkeypatch,clock)
    engine.initialize_runtime()
    with database.get_db_connection() as c:
        c.execute('UPDATE scanner_accounts SET cash=0');c.commit()
    scanner.run_scan()
    assert rows('SELECT status FROM scanner_signals')==[{'status':'RISK_BLOCKED'}]
    assert not rows('SELECT id FROM scanner_orders') and not rows('SELECT id FROM scanner_fills')


def test_fixed_ai_quota_and_default_off(db, clock, monkeypatch):
    c,review,_,_=setup_price(monkeypatch,clock)
    review.return_value['action']='HOLD'
    population=[dict(copy.deepcopy(c),ticker=f'TEST{i:03}') for i in range(30)]
    monkeypatch.setattr(scanner,'load_universe',lambda:{r['ticker']:dict(company=r['company'],indexes=[]) for r in population})
    monkeypatch.setattr(entry_discovery,'discover_candidates',lambda *a,**kw:(copy.deepcopy(population),[]))
    result=scanner.run_scan()
    assert result['ai_selected_count']==review.call_count==scanner.settings()['ai_candidate_limit']==6
    assert not rows('SELECT id FROM scanner_orders')
    monkeypatch.delenv(policy.FLAG)
    assert not policy.enabled() and scanner.settings()['price_news_context_enabled'] is False


@pytest.mark.parametrize('body', [{}, {'news':None}, {'news':{}}, {'news':False},
    {'finance':{'error':{'code':'Unauthorized'}}}, {'news':[], 'error':'synthetic failure'}])
def test_actual_yahoo_parser_never_calls_malformed_http200_an_empty_success(db, clock, monkeypatch, body):
    c, _, _, _=setup_price(monkeypatch,clock)
    response=Mock();response.json.return_value=body
    session=Mock(headers={});session.get.return_value=response
    monkeypatch.setattr(scanner.requests,'Session',lambda:session)
    # Undo the fixture's function mock; exercise the actual parser.
    monkeypatch.setattr(scanner,'fetch_recent_news',REAL_NEWS_FETCH)
    ranked, blocked=enrich(c)
    assert not ranked and blocked[0]['reason']=='news_provider_unavailable_fail_closed'


def test_actual_yahoo_explicit_empty_success(db, clock, monkeypatch):
    c, _, _, _=setup_price(monkeypatch,clock)
    response=Mock();response.json.return_value={'news':[]}
    session=Mock(headers={});session.get.return_value=response
    monkeypatch.setattr(scanner.requests,'Session',lambda:session)
    monkeypatch.setattr(scanner,'fetch_recent_news',REAL_NEWS_FETCH)
    ranked, blocked=enrich(c)
    assert not blocked and ranked[0]['news_context']['availability']=='NO_ELIGIBLE_STORIES'


@pytest.mark.parametrize('items', [{}, None, False, []])
def test_old_or_malformed_cache_cannot_prove_successful_empty(db, clock, monkeypatch, items):
    c, _, _, _=setup_price(monkeypatch,clock)
    monkeypatch.setattr(scanner,'_read_news_cache',lambda:{'TEST':dict(fetched_at=clock.instant.timestamp(),items=items)})
    failure=Mock(side_effect=RuntimeError('synthetic unavailable fresh lookup'))
    monkeypatch.setattr(scanner,'fetch_recent_news',failure)
    ranked, blocked=enrich(c)
    failure.assert_called_once()
    assert not ranked and blocked


@pytest.mark.parametrize('value', [{}, {'TEST':None}, {'TEST':False}, {'TEST':{}}])
def test_incomplete_canonical_mapping_is_unknown_not_empty(db, clock, monkeypatch, value):
    c, _, _, _=setup_price(monkeypatch,clock)
    monkeypatch.setattr('signal_news.existing_news',lambda *a,**kw:value)
    ranked, blocked=enrich(c)
    assert not ranked and blocked[0]['reason']=='news_evidence_unavailable_fail_closed'


def test_recovery_preserves_execution_but_intentionally_omits_news_policy_history(db, clock, monkeypatch):
    _, _, _, price=setup_price(monkeypatch,clock)
    assert scanner.run_scan()['signals_published']==1
    clock.instant+=timedelta(minutes=10)
    engine.process_bar('TEST',dict(at='2026-10-06T14:05:00Z',open=price,high=price+.2,low=price-.1,close=price))
    import active_snapshot, recovery_state
    source=active_snapshot.export_data(database._SQLITE_DB_PATH)
    snapshot=recovery_state.sanitize(source)
    assert snapshot['version']==8  # Unchanged execution contract, no emergency history.
    assert recovery_state.validate(snapshot)['scanner_trades']==1
    original=json.loads(rows('SELECT technical_json FROM scanner_signals')[0]['technical_json'])
    retained=json.loads(snapshot['tables']['scanner_signals'][0]['technical_json'])
    assert policy.retained_metadata(original)
    assert 'news_context' not in retained and 'observed_entry_discovery' not in retained
    assert retained['entry_discovery']==original['entry_discovery']
    assert retained['entry_strategy_execution']==original['entry_strategy_execution']
    assert snapshot['tables']['scanner_signals'][0]['news_json']=='[]'
    corrupt=copy.deepcopy(original)
    corrupt['observed_entry_discovery']['detections'][0]['sourcehash']='a'*64
    with pytest.raises(ValueError,match='retained_attribution_mismatch'):
        policy.retained_metadata(corrupt)
