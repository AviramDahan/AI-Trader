"""Real isolated PG publisher/dispatch routing; mock Telegram, no providers/AI."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from test_news_events_runtime import live


@pytest.fixture
def sender(monkeypatch):
    import stock_scanner
    for key,value in dict(TELEGRAM_BOT_TOKEN='fixture',TELEGRAM_CHAT_ID='fixture',
        TELEGRAM_COMPANY_REPORTS_THREAD_ID='456',TELEGRAM_MARKET_NEWS_THREAD_ID='123',
        TELEGRAM_PERSONAL_NEWS_THREAD_ID='124',TELEGRAM_STOCK_NEWS_THREAD_ID='125').items():
        monkeypatch.setenv(key,value)
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    session=Mock();session.post.return_value.raise_for_status.return_value=None
    monkeypatch.setattr(stock_scanner.requests,'Session',lambda:session)
    return session


def test_canonical_revalidated_earnings_uses_company_topic(live,sender):
    from news_events.engine import Analysis
    from news_events.runtime import queue_outbox
    import scanner_engine
    p,src,result,at,_=live
    eid=p.ingest(src,at);p.analyze(eid,lambda _:Analysis(result),at)
    assert queue_outbox(p,eid,at)==1
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert sender.post.call_args.kwargs['data']['message_thread_id']==456
    assert scanner_engine.process_telegram_outbox()['sent']==0
    with p.store.transaction() as c:
        row=c.execute('SELECT event_type,status FROM scanner_telegram_outbox').fetchone()
        assert row['event_type']=='stock_news' and row['status']=='sent'
        for table in ('scanner_orders','scanner_trades','scanner_signals'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0


def test_company_destination_does_not_bypass_membership_change(live,sender):
    from news_events.engine import Analysis
    from news_events.runtime import queue_outbox
    import scanner_engine
    p,src,result,at,members=live
    eid=p.ingest(src,at);p.analyze(eid,lambda _:Analysis(result),at);queue_outbox(p,eid,at)
    members[1].add('AAPL')
    assert scanner_engine.process_telegram_outbox()['sent']==0
    sender.post.assert_not_called()


def test_two_eligible_original_topics_converge_once(live,sender,monkeypatch):
    from news_events.engine import Pipeline,Analysis
    from news_events.runtime import queue_outbox
    from news_events import runtime
    import scanner_engine
    original,src,result,at,members=live
    members[0].add('AAPL')
    catalog={**original.universe,'MSFT':{'company':'Microsoft Corporation','cik':'789019'}}
    p=Pipeline(original.store,catalog,lambda:members,not_before=original.not_before)
    monkeypatch.setattr(runtime,'pipeline',lambda:p)
    src=replace(src,title='Apple Inc. and Microsoft Corporation financial results',
        source_excerpt='Apple Inc. and Microsoft Corporation reported quarterly financial results with revenue of 100 million dollars each for the latest quarter.',
        tickers=('AAPL','MSFT'))
    eid=p.ingest(src,at);p.analyze(eid,lambda _:Analysis(result),at)
    assert queue_outbox(p,eid,at)==2
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert sender.post.call_count==1
    with p.store.transaction() as c:
        states=[r['status'] for r in c.execute('SELECT status FROM scanner_telegram_outbox ORDER BY id')]
        assert states==['sent','cancelled']
