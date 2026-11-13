"""Analyst destinations: synthetic retained facts, mocked Telegram, no AI."""
import json
from unittest.mock import Mock

import pytest

from test_sec_public_editorial import isolated
from test_earnings_news_routing import dispatch
from test_directional_news_routing import canonical, canonical_row
from test_directional_news_routing import legacy


@pytest.fixture(autouse=True)
def analyst_topic(monkeypatch):
    import requests
    from news_events.analysis import CanonicalAnalyzer
    monkeypatch.setattr(requests.sessions.Session,'request',lambda *_a,**_k:pytest.fail('No external IO'))
    monkeypatch.setattr(CanonicalAnalyzer,'__call__',lambda *_a,**_k:pytest.fail('Routing cannot call AI'))
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','true')
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_THREAD_ID','880')


@pytest.mark.parametrize('headline',[
    'UBS upgrades Apple to Buy from Neutral',
    'Morgan Stanley downgrades AAPL to Equal Weight from Overweight',
    'JPMorgan initiates coverage of Acme at Overweight',
    'Analyst raises AAPL price target to $250 from $220',
    'AAPL price target cut to $180 from $210 at UBS',
    'מורגן סטנלי העלה את מחיר היעד של אפל ל־250 דולר',
    'UBS הוריד את המלצתו למניית אפל למכירה',
    'גולדמן זאקס החל לסקר את אפל בהמלצת קנייה',
])
def test_supported_analyst_actions(headline):
    from news_analyst_routing import is_analyst_update
    assert is_analyst_update(headline)


def test_original_excerpt_can_confirm_rating_but_cannot_promote_product_upgrade():
    from news_analyst_routing import is_analyst_update
    context='The bank moved its stock rating from Neutral to Buy after its review.'
    assert is_analyst_update('UBS upgrades Apple',context)
    assert not is_analyst_update('Apple upgrades its software',context)
    assert not is_analyst_update('Apple opens new factory',context)


@pytest.mark.parametrize('headline',[
    'Apple upgrades its software for new devices',
    'My trading plan: buy AAPL with price target $250 and stop $190',
    'Could analysts raise Apple price target after next earnings?',
    'Analyst expects Apple revenue to rise next quarter',
    'Apple shares rise ahead of analyst conference',
    'Moody\'s upgrades government debt credit rating',
    'The company raises its revenue target for 2027',
    'יעד הכניסה שלי לאפל הוא 220 דולר והסטופ הוא 210',
    'האם האנליסטים יעלו את מחיר היעד של אפל?',
])
def test_speculation_product_upgrades_and_trade_plans_are_not_analyst_news(headline):
    from news_analyst_routing import is_analyst_update
    assert not is_analyst_update(headline)


def test_sender_analyst_destination_and_missing_target_fail_closed(dispatch,monkeypatch):
    import stock_scanner
    assert stock_scanner.send_telegram('UBS upgrades Apple to Buy from Neutral',{'telegram_enabled':True},'market_news')=='sent'
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==880
    monkeypatch.delenv('TELEGRAM_ANALYST_UPDATES_THREAD_ID')
    dispatch.post.reset_mock()
    result=stock_scanner.send_telegram('UBS upgrades Apple to Buy from Neutral',{'telegram_enabled':True},'stock_news')
    assert 'analyst_topic_not_configured' in result
    dispatch.post.assert_not_called()


def test_reports_take_priority_and_personal_sec_trump_are_unchanged(dispatch):
    import stock_scanner
    for kind,text,expected in [('market_news','Synthetic reports Q3 revenue of 100 million; analyst raises price target',456),
        ('position_news','UBS upgrades Apple to Buy from Neutral',None),
        ('trump_truth_post','UBS upgrades Apple to Buy from Neutral',123)]:
        stock_scanner.send_telegram(text,{'telegram_enabled':True},kind)
        if expected is not None:assert dispatch.post.call_args.kwargs['data']['message_thread_id']==expected


def test_flag_off_is_exact_compatibility(dispatch,monkeypatch):
    import stock_scanner
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','false')
    assert stock_scanner.send_telegram('UBS upgrades Apple to Buy from Neutral',{'telegram_enabled':True},'market_news')=='sent'
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==123


def test_canonical_actual_analyst_target_bound_even_when_direction_disabled(canonical,isolated,dispatch,monkeypatch):
    from news_events import runtime
    import scanner_engine
    p,eid,at,result=canonical
    event=p.store.event(eid)['body']
    for source in event['sources']:
        source.update(title='UBS upgrades Synthetic Inc. to Buy from Neutral',event_type='analyst_action')
    event.update(title=event['sources'][0]['title'],event_type='analyst_action')
    result.update(title_he='האנליסט שדרג את המלצתו למניית החברה לקנייה',summary_he='הבנק שינה את ההמלצה מניטרלי לקנייה.')
    with isolated() as c:
        c.execute('UPDATE ne_events SET body_json=?',(json.dumps(event),))
        c.execute('UPDATE ne_analysis SET result_json=?',(json.dumps(result),));c.commit()
    monkeypatch.setenv('TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED','false')
    assert runtime.queue_outbox(p,eid,at)==1
    row=canonical_row(isolated)
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==880
    assert canonical_row(isolated)['dedupe_key']==row['dedupe_key']


def test_canonical_prepared_keys_cancel_on_analyst_destination_change(canonical,isolated,dispatch,monkeypatch):
    from news_events import runtime
    import scanner_engine
    p,eid,at,_=canonical;event=p.store.event(eid)['body']
    for source in event['sources']:source.update(title='UBS raises Synthetic Inc. price target to $250',event_type='analyst_action')
    event.update(title=event['sources'][0]['title'],event_type='analyst_action')
    with isolated() as c:c.execute('UPDATE ne_events SET body_json=?',(json.dumps(event),));c.commit()
    assert runtime.queue_outbox(p,eid,at)==1
    key=canonical_row(isolated)['dedupe_key']
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_THREAD_ID','881')
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert canonical_row(isolated)['status']=='cancelled'
    assert canonical_row(isolated)['dedupe_key']==key
    assert runtime.queue_outbox(p,eid,at)==0
    dispatch.post.assert_not_called()


def test_legacy_retained_source_routes_translation_and_coalesces_exact_broad_peer(isolated,dispatch):
    import scanner_engine
    original=legacy(isolated)
    with isolated() as c:
        c.execute("UPDATE scanner_news SET title='UBS upgrades Synthetic Inc. to Buy from Neutral',analysis_status='public_translated'")
        scanner_engine.enqueue_telegram(c.cursor(),'market-news:1:'+'a'*64,'market_news','הבנק שינה את המלצתו לחברה.')
        c.commit()
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==880
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert dispatch.post.call_count==1
    with isolated() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id')]
    assert rows[0]['dedupe_key']==original['dedupe_key'] and rows[0]['event_type']=='stock_news'
    assert rows[1]['status']=='cancelled' and rows[1]['last_error']=='analyst_update_already_sent'


def test_legacy_different_multiissuer_subsets_are_not_collapsed(isolated,dispatch):
    import scanner_engine
    legacy(isolated,verified_tickers_json='["TEST","OTHER"]')
    with isolated() as c:
        c.execute("UPDATE scanner_news SET title='UBS raises TEST and OTHER price targets to $250'")
        scanner_engine.enqueue_telegram(c.cursor(),'stock-news:1:'+'a'*64+':OTHER','stock_news','הבנק העלה את מחיר היעד לחברה האחרת.')
        c.commit()
    assert scanner_engine.process_telegram_outbox()['sent']==2
    assert dispatch.post.call_count==2
    assert {call.kwargs['data']['message_thread_id'] for call in dispatch.post.call_args_list}=={880}


def test_ambiguous_analyst_receipt_blocks_other_broad_route_without_resend(isolated,dispatch):
    import scanner_engine,requests
    legacy(isolated)
    with isolated() as c:
        c.execute("UPDATE scanner_news SET title='UBS upgrades Synthetic Inc. to Buy from Neutral'")
        scanner_engine.enqueue_telegram(c.cursor(),'market-news:1:'+'a'*64,'market_news','שינוי המלצה.');c.commit()
    dispatch.post.side_effect=requests.ReadTimeout('synthetic')
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert dispatch.post.call_count==1
    with isolated() as c:
        assert [r['status'] for r in c.execute('SELECT status FROM scanner_telegram_outbox ORDER BY id')]==['failed','cancelled']


def test_analyst_source_cannot_bypass_canonical_publisher_fence(isolated,dispatch,monkeypatch):
    import scanner_engine
    from news_events import control
    legacy(isolated,title='UBS upgrades Synthetic Inc. to Buy from Neutral')
    monkeypatch.setattr(control,'active',lambda:True)
    assert scanner_engine.process_telegram_outbox()['sent']==0
    dispatch.post.assert_not_called()


def test_missing_source_or_wrong_review_version_never_acquires_source_hint(isolated):
    from news_analyst_routing import analyst_for_outbox
    row=legacy(isolated,title='UBS upgrades Synthetic Inc. to Buy from Neutral')
    assert analyst_for_outbox(row)
    row['dedupe_key']=row['dedupe_key'].replace('a'*64,'b'*64)
    assert not analyst_for_outbox(row)
    row['dedupe_key']='stock-news:999:'+'a'*64+':TEST'
    assert not analyst_for_outbox(row)


@pytest.mark.parametrize('kind,topic', [('position_news',300),('watchlist_news',300),('sec_intelligence',400),
    ('entry',700),('new_signal',600),('news_status',99)])
def test_unrelated_routes_never_redirect_even_with_analyst_hint(dispatch,monkeypatch,kind,topic):
    import stock_scanner
    for key,value in {'TELEGRAM_PERSONAL_NEWS_THREAD_ID':'300','TELEGRAM_SEC_INTELLIGENCE_THREAD_ID':'400',
        'TELEGRAM_AGENT_ACTIONS_THREAD_ID':'700','TELEGRAM_SIGNALS_THREAD_ID':'600','TELEGRAM_STOCK_NEWS_THREAD_ID':'99'}.items():monkeypatch.setenv(key,value)
    assert stock_scanner.send_telegram('UBS upgrades Apple to Buy from Neutral',{'telegram_enabled':True},kind,analyst_update=True)=='sent'
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==topic


def test_canonical_same_fact_alias_does_not_replay_prior_broad_delivery_at_cutover(canonical,isolated,dispatch,monkeypatch):
    from news_events import runtime
    import scanner_engine
    p,eid,at,_=canonical;event=p.store.event(eid)['body']
    for source in event['sources']:source.update(title='UBS raises Synthetic Inc. price target to $250',event_type='analyst_action')
    event.update(title=event['sources'][0]['title'],event_type='analyst_action')
    with isolated() as c:c.execute('UPDATE ne_events SET body_json=?',(json.dumps(event),));c.commit()
    monkeypatch.setenv('TELEGRAM_STOCK_NEWS_THREAD_ID','123')
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','false')
    assert runtime.queue_outbox(p,eid,at)==1
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==123
    alias='synthetic-alias'
    with isolated() as c:
        c.execute('''INSERT INTO ne_events SELECT ?,body_json,evidence_version,status,reason,created_at,updated_at
                     FROM ne_events WHERE event_id=?''',(alias,eid))
        c.execute('''INSERT INTO ne_analysis SELECT ?,version,status,result_json,error,started_at,finished_at,latency,owner
                     FROM ne_analysis WHERE event_id=?''',(alias,eid));c.commit()
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED','true')
    assert runtime.queue_outbox(p,alias,at)==1
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert dispatch.post.call_count==1
    with isolated() as c:
        latest=dict(c.execute('SELECT * FROM scanner_telegram_outbox ORDER BY id DESC LIMIT 1').fetchone())
    assert latest['status']=='cancelled' and latest['last_error']=='analyst_update_already_sent'


def test_topic_id_alone_does_not_enable_routing(dispatch,monkeypatch):
    import stock_scanner
    monkeypatch.delenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED')
    assert stock_scanner.send_telegram('UBS upgrades Apple to Buy from Neutral',{'telegram_enabled':True},'market_news')=='sent'
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==123


@pytest.mark.parametrize('headline',[
    'Citigroup Adjusts International Flavors & Fragrances PT to $105 From $100',
    'Maxim Adjusts Price Target on Gilead Sciences to $200 From $165',
    'Wells Fargo Adjusts Fidelity National Information Services PT to $33 From $46',
    'BofA Adjusts Example PT to $105 from $100, Maintains Neutral',
])
def test_dated_adjusted_price_target_source_family(headline):
    from news_analyst_routing import is_analyst_update
    assert is_analyst_update(headline)


@pytest.mark.parametrize('headline',[
    'Physical therapist adjusts PT to 20 from 10 minutes',
    'BofA maintains Example PT at $105',
    'BofA adjusts Example PT to $105 from $105',
    'BofA may adjust Example PT to $105 from $100',
])
def test_pt_abbreviation_is_not_guessed_or_static_target_invented(headline):
    from news_analyst_routing import is_analyst_update
    assert not is_analyst_update(headline)


def test_attached_analyst_source_cannot_lend_identity_to_current_unrelated_headline():
    from news_analyst_routing import analyst_event
    assert not analyst_event({'title':'Example opens a factory','sources':[
        {'title':'Example opens a factory','source_excerpt':'A new factory opens.'},
        {'title':'UBS upgrades Example to Buy from Neutral','source_excerpt':'A prior analyst update.'}]})


def test_real_phase1_version_generator_is_supported_without_loose_lengths(isolated):
    from news_analyst_routing import analyst_for_outbox
    from news_pipeline import _event_version
    title='UBS upgrades Synthetic Inc. to Buy from Neutral'
    version=_event_version({'title':title,'source_excerpt':'The stock rating was changed from Neutral to Buy.'})
    assert len(version)==20
    row=legacy(isolated,version=version,title=title)
    assert analyst_for_outbox(row)
    row['dedupe_key']=row['dedupe_key'].replace(version,version+'a')
    assert not analyst_for_outbox(row)


@pytest.mark.parametrize('suffix', ['TEST,TEST','TEST,OTHER','test','UNKNOWN','TEST:extra',''])
def test_analyst_stock_audience_must_be_valid_sorted_unique_verified(isolated,suffix):
    from news_analyst_routing import analyst_for_outbox
    row=legacy(isolated,title='UBS upgrades Synthetic Inc. to Buy from Neutral')
    row['dedupe_key']='stock-news:1:'+'a'*64+':'+suffix
    assert not analyst_for_outbox(row)


def test_analyst_key_family_cannot_change_durable_news_kind(isolated):
    from news_analyst_routing import analyst_for_outbox
    row=legacy(isolated,title='UBS upgrades Synthetic Inc. to Buy from Neutral')
    row['dedupe_key']='market-news:1:'+'a'*64
    assert not analyst_for_outbox(row)


@pytest.mark.parametrize('headline,body,expected',[
    ('Example Q2 Earnings Beat Estimates','',True),
    ('Example Q2 Earnings Miss Estimates as Costs Rise','',True),
    ('Could Example Q2 Earnings Beat Estimates?','',False),
    ('Example Q2 Earnings Could Beat Estimates','',False),
    ('Example Financial Results Conference to Be Held on Friday','',False),
    ('Example Financial Results Conference','',False),
    ('Example Q2 Earnings Call Transcript','',False),
    ('Example unveils new beta app','Forward-looking statements could differ from actual financial results.',False),
    ('Example publishes an update','The company reported Q2 revenue of 100 million dollars.',True),
    ('Example publishes an update','The company will report Q2 revenue next week.',False),
])
def test_report_actual_results_do_not_borrow_previews_or_disclaimers(headline,body,expected):
    from news_report_routing import is_company_report
    assert is_company_report(headline,body) is expected


def test_twenty_hex_report_peers_converge_once_and_preserve_original_keys(isolated,dispatch):
    from news_pipeline import _event_version
    import scanner_engine
    title='Example Q2 Earnings Beat Estimates'
    version=_event_version({'title':title})
    with isolated() as c:
        for key,kind in [('market-news:100:'+version,'market_news'),('stock-news:100:'+version+':TEST','stock_news')]:
            scanner_engine.enqueue_telegram(c.cursor(),key,kind,title)
        c.commit()
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert dispatch.post.call_count==1
    with isolated() as c:
        assert [r['status'] for r in c.execute('SELECT status FROM scanner_telegram_outbox ORDER BY id')]==['sent','cancelled']


def test_current_canonical_report_identity_does_not_borrow_old_attached_source(canonical,monkeypatch):
    from news_events import runtime
    from news_report_routing import REPORT_PREFIX, CONTROLS
    p,eid,_,result=canonical;event=p.store.event(eid)['body']
    original=event['sources'][0]
    event['sources'].append({**original,'title':'Example Q2 Earnings Beat Estimates',
                             'source_excerpt':'The company reported Q2 earnings above estimates.'})
    assert not CONTROLS.sub('',runtime.message(event,result,'important_stock_news',['TEST'])).startswith(REPORT_PREFIX)
    destinations=[]
    from news_events import general_news
    monkeypatch.setattr(general_news,'publication_keys',lambda _e,_v,d:destinations.append(d) or ['fixture'])
    runtime.general_publication_keys(event,'a'*64,'important_stock_news',result)
    assert destinations[-1][1]!=456


def test_current_original_report_keeps_report_destination_with_sparse_hebrew(canonical,monkeypatch):
    from news_events import runtime
    from news_report_routing import REPORT_PREFIX, CONTROLS
    from news_events import general_news
    p,eid,_,result=canonical;event=p.store.event(eid)['body']
    event['title']='Example Q2 Earnings Beat Estimates'
    event['source_excerpt']='The company reported Q2 earnings above estimates.'
    event['sources'][0].update(title=event['title'],source_excerpt=event['source_excerpt'])
    result.update(title_he='עדכון מהחברה',summary_he='פורסמו נתונים חדשים.')
    assert CONTROLS.sub('',runtime.message(event,result,'important_stock_news',['TEST'])).startswith(REPORT_PREFIX)
    destinations=[]
    monkeypatch.setattr(general_news,'publication_keys',lambda _e,_v,d:destinations.append(d) or ['fixture'])
    runtime.general_publication_keys(event,'a'*64,'important_stock_news',result)
    assert destinations[-1][1]==456
