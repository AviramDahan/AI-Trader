"""News-result destination checks, synthetic facts and mocked Telegram only."""
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from news_report_routing import is_company_report, delivery_type
from test_sec_public_editorial import isolated

TEXT='Synthetic reported Q3 revenue of 100 million dollars'
VERSION='a'*64


@pytest.fixture
def dispatch(monkeypatch):
    import stock_scanner
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME','false')
    for key,value in dict(TELEGRAM_BOT_TOKEN='fixture',TELEGRAM_CHAT_ID='fixture',
                         TELEGRAM_COMPANY_REPORTS_THREAD_ID='456',TELEGRAM_MARKET_NEWS_THREAD_ID='123').items():
        monkeypatch.setenv(key,value)
    monkeypatch.setattr(stock_scanner,'settings',lambda:{'telegram_enabled':True})
    session=Mock();session.post.return_value.raise_for_status.return_value=None
    monkeypatch.setattr(stock_scanner.requests,'Session',lambda:session)
    return session


def pending(connect, news_id, version=VERSION):
    import scanner_engine
    with connect() as conn:
        assert scanner_engine.enqueue_telegram(conn.cursor(),f'market-news:{news_id}:{version}','market_news',TEXT)
        assert scanner_engine.enqueue_telegram(conn.cursor(),f'stock-news:{news_id}:{version}:TEST','stock_news',TEXT)
        conn.commit()


@pytest.mark.parametrize('title,summary',[
    ('Synthetic Oil דיווחה על רווחים ברבעון השלישי','רווח למניה מתואם של 2.10 דולר.'),
    ('Synthetic Bank פרסמה את תוצאותיה לרבעון השלישי','הכנסות ריבית נטו של 4 מיליארד דולר.'),
    ('Synthetic Auto מדווחת על תוצאות רבעון שלישי','הכנסות של 60 מיליארד אירו והפסד תפעולי.'),
    ('Synthetic Q3 financial results','Reported revenue rose to 100 million dollars.'),
    ('SYN 3Q ADJ EPS $2.10, EST. $2.00',''),
    ('Synthetic annual financial results',''),
    ('Synthetic reports Q3 revenue and raises guidance','The company will host a call tomorrow.'),
])
def test_company_results_are_routed_independently_of_verified_ticker(title,summary):
    assert is_company_report(title,summary)
    assert delivery_type('market_news',title+'\n\n'+summary)=='company_report'


@pytest.mark.parametrize('title,summary',[
    ('Australia Q3 import prices fell 1.1%',''),
    ('מחירי הייצוא של אוסטרליה עלו ברבעון השלישי','הנתון משפיע על יבואנים.'),
    ('US Q3 GDP rises 3.1%',''),
    ('US GDP quarterly results','The government reported GDP growth of 3.1%.'),
    ('Government reports Q3 tax revenue','Tax revenue rose to 100 billion dollars.'),
    ('Synthetic will report Q3 earnings tomorrow','Revenue last year was 100 million dollars.'),
    ('Synthetic announces date for quarterly financial results','Call scheduled for next month.'),
    ('Synthetic clinical trial quarterly results','The treatment met its primary endpoint.'),
    ('Fed holds interest rates',''),
    ('Synthetic analyst raises price target','EPS estimates for the next quarter were raised.'),
    ('Synthetic reports acquisition','The deal is expected to increase EPS next quarter.'),
])
def test_macro_previews_and_other_corporate_news_stay_news(title,summary):
    assert not is_company_report(title,summary)
    assert delivery_type('market_news',title+'\n\n'+summary)=='market_news'


def test_interpretation_alone_cannot_reclassify_macro_as_company_results():
    text='📰 פורסמו נתוני יבוא רבעוניים\n\nמשמעות אפשרית לסוחר (AI): חברה דיווחה הכנסות ורווח למניה ברבעון.'
    assert delivery_type('market_news',text)=='market_news'


@pytest.mark.parametrize('kind',['new_signal','entry','tp','stop','sell','trump_truth_post','sec_intelligence',None])
def test_non_news_routes_are_never_reclassified(kind):
    assert delivery_type(kind,'Synthetic reported Q3 revenue of 100 million dollars')==kind


@pytest.mark.parametrize('kind',['market_news','stock_news','position_news','watchlist_news'])
def test_actual_generic_sender_uses_report_topic_for_every_news_path(monkeypatch,kind):
    import stock_scanner
    for key,value in dict(TELEGRAM_BOT_TOKEN='fixture',TELEGRAM_CHAT_ID='fixture',
        TELEGRAM_COMPANY_REPORTS_THREAD_ID='456',TELEGRAM_MARKET_NEWS_THREAD_ID='123',
        TELEGRAM_STOCK_NEWS_THREAD_ID='123',TELEGRAM_PERSONAL_NEWS_THREAD_ID='123').items():
        monkeypatch.setenv(key,value)
    session=Mock();monkeypatch.setattr(stock_scanner.requests,'Session',lambda:session)
    text='Synthetic reported Q3 revenue of 100 million dollars'
    assert stock_scanner.send_telegram(text,{'telegram_enabled':True},kind)=='sent'
    assert session.post.call_args.kwargs['data']['message_thread_id']==456


def test_missing_report_topic_does_not_fall_back_to_news(monkeypatch):
    import stock_scanner
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','fixture');monkeypatch.setenv('TELEGRAM_CHAT_ID','fixture')
    monkeypatch.delenv('TELEGRAM_COMPANY_REPORTS_THREAD_ID',raising=False)
    monkeypatch.setattr(stock_scanner.requests,'Session',Mock(side_effect=AssertionError('no send')))
    result=stock_scanner.send_telegram('Synthetic reported Q3 revenue of 100 million dollars',
                                     {'telegram_enabled':True},'market_news')
    assert 'company_reports_topic_not_configured' in result


def test_old_pending_routes_converge_once_and_restart_does_not_repeat(isolated,dispatch):
    import scanner_engine
    pending(isolated,901)
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert scanner_engine.process_telegram_outbox()['sent']==0
    assert dispatch.post.call_count==1
    assert dispatch.post.call_args.kwargs['data']['message_thread_id']==456
    with isolated() as conn:
        rows=conn.execute('SELECT event_type,status,last_error FROM scanner_telegram_outbox ORDER BY id').fetchall()
        assert rows[0]['event_type']=='market_news' and rows[0]['status']=='sent'
        assert rows[1]['event_type']=='stock_news' and rows[1]['status']=='cancelled'
        assert rows[1]['last_error']=='company_report_already_sent'
        assert conn.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']==0


def test_ambiguous_receipt_blocks_other_route_without_claiming_delivery(isolated,dispatch):
    import scanner_engine, requests
    pending(isolated,902)
    dispatch.post.side_effect=requests.ReadTimeout('synthetic')
    result=scanner_engine.process_telegram_outbox()
    assert result['sent']==0 and result['failed']==1 and dispatch.post.call_count==1
    assert scanner_engine.process_telegram_outbox()['sent']==0
    with isolated() as conn:
        assert [r['status'] for r in conn.execute('SELECT status FROM scanner_telegram_outbox ORDER BY id')]==['failed','cancelled']


def test_new_evidence_version_is_not_suppressed_as_old_report(isolated,dispatch):
    import scanner_engine
    pending(isolated,903)
    assert scanner_engine.process_telegram_outbox()['sent']==1
    pending(isolated,903,'b'*64)
    assert scanner_engine.process_telegram_outbox()['sent']==1
    assert dispatch.post.call_count==2


def test_report_heading_cannot_bypass_canonical_publisher_fence(isolated,dispatch,monkeypatch):
    import scanner_engine
    pending(isolated,904)
    from news_events import control
    monkeypatch.setattr(control,'active',lambda:True)
    assert scanner_engine.process_telegram_outbox()['sent']==0
    dispatch.post.assert_not_called()


def test_report_cannot_bypass_personal_membership_revalidation(isolated,dispatch):
    import scanner_engine
    with isolated() as conn:
        assert scanner_engine.enqueue_telegram(conn.cursor(),f'watchlist-news:999:{VERSION}:TEST','watchlist_news',TEXT)
        conn.commit()
    assert scanner_engine.process_telegram_outbox()['sent']==0
    dispatch.post.assert_not_called()
