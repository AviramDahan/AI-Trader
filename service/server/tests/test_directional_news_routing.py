"""Destination only: retained synthetic evidence, no models or external IO."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from test_earnings_news_routing import dispatch
from test_sec_public_editorial import isolated

VERSION = 'a' * 64
RESULT = dict(related=True, sentiment='positive', materiality='high', relevance=.9)


@pytest.fixture(autouse=True)
def topics(monkeypatch):
    import requests
    from news_events.analysis import CanonicalAnalyzer
    monkeypatch.setattr(requests.sessions.Session,'request',lambda *_a,**_k: pytest.fail('No external IO in routing tests'))
    monkeypatch.setattr(CanonicalAnalyzer,'__call__',lambda *_a,**_k: pytest.fail('Routing must not call AI'))
    for key, value in dict(TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED='true',
            TELEGRAM_POSITIVE_STOCK_NEWS_THREAD_ID='201', TELEGRAM_NEGATIVE_STOCK_NEWS_THREAD_ID='202',
            TELEGRAM_MARKET_NEWS_THREAD_ID='100', TELEGRAM_STOCK_NEWS_THREAD_ID='99',
            TELEGRAM_PERSONAL_NEWS_THREAD_ID='300', TELEGRAM_SEC_INTELLIGENCE_THREAD_ID='400',
            TELEGRAM_COMPANY_REPORTS_THREAD_ID='500', TELEGRAM_SIGNALS_THREAD_ID='600',
            TELEGRAM_AGENT_ACTIONS_THREAD_ID='700', TELEGRAM_CHAT_ID='fixture').items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize('direction,expected', [('positive',201), ('negative',202), (None,100), ('mixed',100)])
def test_directional_destination_does_not_change_durable_type(direction, expected):
    from telegram_topics import destination_fields
    assert destination_fields('fixture','stock_news',stock_direction=direction)['message_thread_id'] == expected


@pytest.mark.parametrize('kind,expected', [('position_news',300), ('watchlist_news',300),
    ('sec_intelligence',400), ('trump_truth_post',100), ('company_report',500), ('entry',700), ('new_signal',600)])
def test_other_destinations_unchanged(kind, expected):
    from telegram_topics import thread_id_for_event
    assert thread_id_for_event(kind,stock_direction='positive') == expected


def test_flag_off_preserves_old_stock_destination(monkeypatch):
    from telegram_topics import thread_id_for_event
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','false')
    assert thread_id_for_event('stock_news',stock_direction='positive') == 99


def legacy(connect, *, version=VERSION, **updates):
    import scanner_engine
    data=dict(fingerprint='fixture',scope='company',title='Synthetic acquisition approved',publisher='fixture',
        url='https://fixture.invalid/news',published_at='2026-11-05T12:00:00Z',fetched_at='2026-11-05T12:00:00Z',
        content_hash=version,analysis_status='analyzed',quality_version=2,verified_tickers_json='["TEST"]',
        sentiment='positive',materiality='high',relevance=.9)
    data.update(updates)
    with connect() as c:
        c.execute('INSERT INTO scanner_news('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')', tuple(data.values()))
        nid=c.execute('SELECT id FROM scanner_news').fetchone()['id']
        key=f'stock-news:{nid}:{version}:TEST'
        assert scanner_engine.enqueue_telegram(c.cursor(),key,'stock_news','Synthetic acquisition approved')
        c.commit()
        return dict(c.execute('SELECT * FROM scanner_telegram_outbox WHERE dedupe_key=?',(key,)).fetchone())


def test_legacy_retained_direction_and_restart_no_resend(isolated, dispatch):
    import scanner_engine
    row=legacy(isolated)
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert dispatch.post.call_args.kwargs['data']['message_thread_id'] == 201
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert dispatch.post.call_count == 1
    with isolated() as c:
        saved=dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
    assert (saved['event_type'],saved['dedupe_key'],saved['status']) == ('stock_news',row['dedupe_key'],'sent')


@pytest.mark.parametrize('updates', [dict(analysis_status='public_translated'),dict(analysis_status='pending'),
    dict(analysis_status='error'),dict(quality_version=0),dict(quality_version=-2),dict(quality_version=99),
    dict(verified_tickers_json='[]'),dict(verified_tickers_json='["OTHER"]'),dict(verified_tickers_json='bad'),
    dict(sentiment='mixed'),dict(materiality='low'),dict(relevance=2),dict(relevance=None),dict(duplicate_of=123)])
def test_unknown_or_unverified_legacy_goes_general(isolated, updates):
    from news_direction_routing import direction_for_outbox
    assert direction_for_outbox(legacy(isolated, **updates)) is None


def test_legacy_audit_version_is_authoritative_not_stored_row_hash(isolated):
    from news_direction_routing import direction_for_outbox
    row=legacy(isolated)
    with isolated() as c:
        c.execute('INSERT INTO news_publication_audit(news_id,content_version,evidence_key,reasons_json,updated_at) VALUES(1,?,?,?,?)',
                  ('b'*64,'fixture','[]','2026-11-05T12:00:00Z'))
        c.commit()
    assert direction_for_outbox(row) is None
    row['dedupe_key']=row['dedupe_key'].replace(VERSION,'b'*64)
    assert direction_for_outbox(row) == 'positive'


@pytest.mark.parametrize('result', [dict(RESULT,relevance=True),dict(RESULT,relevance='0.9'),
    dict(RESULT,relevance=float('nan')),dict(RESULT,relevance=float('inf')),dict(RESULT,related=False),
    dict(RESULT,_public_translation_only=True),dict(RESULT,sentiment='neutral')])
def test_invalid_analysis_never_becomes_direction(result):
    from news_direction_routing import direction_for_result
    assert direction_for_result({'tickers':['TEST'],'company_identity':[{'ticker':'TEST'}]},result) is None


def test_report_override_wins_over_direction(dispatch):
    import stock_scanner
    assert stock_scanner.send_telegram('Synthetic reported Q3 revenue of 100 million dollars',
        {'telegram_enabled':True},'stock_news',stock_direction='positive') == 'sent'
    assert dispatch.post.call_args.kwargs['data']['message_thread_id'] == 456


def test_general_key_encodes_effective_direction_only_when_enabled(monkeypatch):
    from news_events import runtime
    from news_events import general_news
    seen=[]
    monkeypatch.setattr(general_news,'publication_keys',lambda event,version,destination: seen.append(destination) or [str(destination)])
    event={'tickers':['TEST'],'company_identity':[{'ticker':'TEST'}]}
    runtime.general_publication_keys(event,VERSION,'important_stock_news',RESULT)
    runtime.general_publication_keys(event,VERSION,'important_stock_news',dict(RESULT,sentiment='negative'))
    runtime.general_publication_keys(event,VERSION,'important_stock_news',dict(RESULT,sentiment='mixed'))
    assert seen == [['fixture',201],['fixture',202],['fixture',100]]
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','false')
    runtime.general_publication_keys(event,VERSION,'important_stock_news',RESULT)
    assert seen[-1] == ['fixture',99]


@pytest.fixture
def canonical(isolated, dispatch, monkeypatch):
    """Real retained canonical queue/send code, synthetic source and no AI."""
    from news_events import runtime
    from news_events.engine import Pipeline
    from news_events.store import Store
    from news_events.model import Source
    at=datetime.now(timezone.utc)
    with isolated() as c:
        schema=Path(runtime.__file__).with_name('schema.sql').read_text()
        for statement in schema.split(';'):
            if statement.strip():c.execute(statement)
        c.execute('CREATE TABLE ne_control(id INTEGER PRIMARY KEY, mode TEXT, not_before TEXT, epoch INTEGER)')
        c.execute('INSERT INTO ne_control VALUES(1,?,?,1)',('canonical',(at-timedelta(days=1)).isoformat()))
        c.execute('CREATE TABLE ne_outbox(dedupe_key TEXT PRIMARY KEY,event_id TEXT,version TEXT,topic TEXT,epoch INTEGER)')
        c.execute('CREATE TABLE ne_cutover_receipts(source_url TEXT,topic TEXT,created_at TEXT)')
        c.commit()
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME','true')
    p=Pipeline(Store(isolated,production=True),{'TEST':{'company':'Synthetic Inc.'},'OTHER':{'company':'Other Inc.'}},
               lambda:[set(),set()],not_before=at-timedelta(days=1))
    monkeypatch.setattr(runtime,'pipeline',lambda:p)
    monkeypatch.setattr(runtime,'now',lambda:at)
    monkeypatch.setattr(runtime,'membership',lambda *_a:(set(),set()))
    item=Source('synthetic','one','https://fixture.invalid/articles/12345','Fixture',at.isoformat(),at.isoformat(),
        'Synthetic Inc. launches a new factory in the United States',
        'Synthetic Inc. announced that it opened its new factory in the United States today and hired local workers.',
        event_type='business_update',rights='approved')
    eid=p.ingest(item,at)
    record=p.store.event(eid)
    result={**RESULT,'title_he':'החברה פתחה מפעל חדש בארצות הברית',
            'summary_he':'החברה דיווחה שפתחה מפעל וגייסה עובדים מקומיים.',
            'interpretation_he':'ייתכן שהמפעל ירחיב את פעילות החברה.'}
    with isolated() as c:
        c.execute("UPDATE ne_events SET status='analyzed',reason=NULL WHERE event_id=?",(eid,))
        c.execute("INSERT INTO ne_analysis(event_id,version,status,result_json,started_at,owner) VALUES(?,?,'done',?,?,?)",
                  (eid,record['evidence_version'],json.dumps(result),at.isoformat(),'synthetic'))
        c.commit()
    return p,eid,at,result


def canonical_row(connect):
    with connect() as c:
        return dict(c.execute("SELECT * FROM scanner_telegram_outbox WHERE event_type='stock_news'").fetchone())


def test_canonical_queue_send_same_analysis_and_restart_no_resend(canonical, isolated, dispatch):
    import scanner_engine
    from news_events.runtime import queue_outbox, general_publication_keys
    from news_direction_routing import direction_for_outbox
    p,eid,at,result=canonical
    assert queue_outbox(p,eid,at) == 1
    row=canonical_row(isolated)
    record=p.store.event(eid)
    assert row['dedupe_key'] in general_publication_keys(record['body'],record['evidence_version'],'important_stock_news',result)
    assert direction_for_outbox(row) == 'positive'
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert dispatch.post.call_args.kwargs['data']['message_thread_id'] == 201
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    assert queue_outbox(p,eid,at) == 0
    assert dispatch.post.call_count == 1


@pytest.mark.parametrize('mutation', ['epoch','version','status','identity','translation','analysis'])
def test_canonical_retained_provenance_never_borrows_other_analysis(canonical,isolated,mutation):
    from news_events.runtime import queue_outbox
    from news_direction_routing import direction_for_outbox
    p,eid,at,result=canonical
    assert queue_outbox(p,eid,at) == 1
    row=canonical_row(isolated)
    with isolated() as c:
        if mutation=='epoch':c.execute('UPDATE ne_control SET epoch=2')
        elif mutation=='version':c.execute('UPDATE ne_events SET evidence_version=?',('b'*64,))
        elif mutation=='status':c.execute("UPDATE ne_events SET status='quality_failed'")
        elif mutation=='analysis':c.execute("UPDATE ne_analysis SET status='running'")
        elif mutation=='translation':
            c.execute('UPDATE ne_analysis SET result_json=?',(json.dumps(dict(result,_public_translation_only=True)),))
        else:
            event=p.store.event(eid)['body'];event['company_identity']=[]
            c.execute('UPDATE ne_events SET body_json=?',(json.dumps(event),))
        c.commit()
    assert direction_for_outbox(row) is None


def test_prepared_canonical_destination_is_not_rewritten_or_replayed(canonical,isolated,dispatch,monkeypatch):
    import scanner_engine
    from news_events.runtime import queue_outbox
    p,eid,at,_=canonical
    assert queue_outbox(p,eid,at) == 1
    old=canonical_row(isolated)
    monkeypatch.setenv('TELEGRAM_POSITIVE_STOCK_NEWS_THREAD_ID','999')
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    saved=canonical_row(isolated)
    assert saved['dedupe_key'] == old['dedupe_key'] and saved['status'] == 'cancelled'
    assert queue_outbox(p,eid,at) == 0
    dispatch.post.assert_not_called()


def test_personal_and_broad_multi_company_subsets_are_not_collapsed(canonical,isolated,dispatch,monkeypatch):
    import scanner_engine
    from news_events import runtime
    p,eid,at,_=canonical
    event=p.store.event(eid)['body']
    event['tickers']=['OTHER','TEST']
    event['company_identity'].append({'ticker':'OTHER','company':'Other Inc.','basis':'legal_name'})
    with isolated() as c:
        c.execute('UPDATE ne_events SET body_json=?',(json.dumps(event),));c.commit()
    p.membership=lambda:[{'TEST'},set()]
    monkeypatch.setattr(runtime,'membership',lambda *_a:({'TEST'},set()))
    assert runtime.queue_outbox(p,eid,at) == 2
    assert scanner_engine.process_telegram_outbox()['sent'] == 2
    assert {call.kwargs['data']['message_thread_id'] for call in dispatch.post.call_args_list} == {201,300}
    with isolated() as c:
        assert [r['tickers_json'] for r in c.execute('SELECT tickers_json FROM ne_delivery ORDER BY topic')] == ['["OTHER"]','["TEST"]']


def test_flag_on_cannot_bypass_existing_publisher_fence(isolated,dispatch,monkeypatch):
    import scanner_engine
    from news_events import control
    legacy(isolated)
    monkeypatch.setattr(control,'active',lambda:True)
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    dispatch.post.assert_not_called()


def test_missing_directional_target_fails_closed_without_general_spill(dispatch,monkeypatch):
    import stock_scanner
    monkeypatch.delenv('TELEGRAM_POSITIVE_STOCK_NEWS_THREAD_ID')
    result=stock_scanner.send_telegram('Synthetic acquisition approved',{'telegram_enabled':True},'stock_news',stock_direction='positive')
    assert 'stock_news_topic_not_configured' in result
    dispatch.post.assert_not_called()


@pytest.mark.parametrize('quality_version',[2,3])
def test_negative_known_quality_and_explicit_v1_supported(isolated,quality_version):
    from news_direction_routing import direction_for_outbox
    row=legacy(isolated,version='v1',quality_version=quality_version,sentiment='negative')
    with isolated() as c:c.execute('UPDATE scanner_news SET content_hash=NULL');c.commit()
    assert direction_for_outbox(row) == 'negative'


@pytest.mark.parametrize('key', ['stock-news:1:'+VERSION+':TEST,OTHER',
    'stock-news:1:'+VERSION+':TEST,TEST','stock-news:1:'+VERSION+':test',
    'stock-news:1:new-version:TEST','stock-news:1:'+VERSION+':TEST:extra','news:1:'+VERSION+':TEST'])
def test_malformed_or_wrong_legacy_identity_does_not_infer_direction(isolated,key):
    from news_direction_routing import direction_for_outbox
    row=legacy(isolated);row['dedupe_key']=key
    assert direction_for_outbox(row) is None


def test_ambiguous_directional_send_is_terminal_and_never_resent(isolated,dispatch):
    import scanner_engine, requests
    legacy(isolated)
    dispatch.post.side_effect=requests.ReadTimeout('synthetic unknown remote outcome')
    assert scanner_engine.process_telegram_outbox() == {'sent':0,'failed':1}
    assert scanner_engine.process_telegram_outbox() == {'sent':0,'failed':0}
    assert dispatch.post.call_count == 1
    with isolated() as c:
        row=dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
    assert row['status'] == 'failed' and row['event_type'] == 'stock_news'


def test_rate_limited_directional_retry_retains_original_identity(isolated,dispatch):
    import scanner_engine, requests
    row=legacy(isolated,sentiment='negative')
    response=requests.Response();response.status_code=429;response.headers['Retry-After']='1'
    response._content=b'{"parameters":{"retry_after":1}}'
    dispatch.post.return_value.raise_for_status.side_effect=requests.HTTPError(response=response)
    assert scanner_engine.process_telegram_outbox() == {'sent':0,'failed':1}
    dispatch.post.return_value.raise_for_status.side_effect=None
    with isolated() as c:
        c.execute("UPDATE scanner_telegram_outbox SET next_attempt_at='2000-01-01T00:00:00Z'");c.commit()
    assert scanner_engine.process_telegram_outbox() == {'sent':1,'failed':0}
    assert {call.kwargs['data']['message_thread_id'] for call in dispatch.post.call_args_list} == {202}
    with isolated() as c:saved=dict(c.execute('SELECT * FROM scanner_telegram_outbox').fetchone())
    assert saved['dedupe_key'] == row['dedupe_key'] and saved['attempts'] == 2


def test_source_report_header_determines_canonical_destination_key(canonical,isolated):
    from news_events import runtime
    from news_events.general_news import publication_keys
    p,eid,at,result=canonical
    record=p.store.event(eid);event=record['body']
    for source in event['sources']:
        source.update(title='Synthetic Inc. reports Q3 revenue of 100 million dollars',event_type='earnings')
    event.update(title=event['sources'][0]['title'],event_type='earnings')
    assert runtime.general_publication_keys(event,record['evidence_version'],'important_stock_news',result) == publication_keys(event,record['evidence_version'],['fixture',456])
