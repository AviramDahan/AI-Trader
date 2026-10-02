"""CI-only synthetic image transition probe; no production credentials or networks.

Mount this script read-only into unmodified application images. All engine modules
come from the image, never copied function snapshots. Providers alone are mocked.
"""
import json,os,sys,subprocess
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import requests
import database,migrations,scanner_engine as e

assert os.environ['DATABASE_URL'].startswith('postgresql://isolated:')
assert os.environ.get('AI_TRADER_CLOUD')=='true'
ROOT=Path('/proof')


def record(ticker):
    return e.record_signal(dict(signal_id=None,ticker=ticker,company=ticker,action='BUY',entry=100,stop_loss=97,
        confidence=.91,time_horizon='weeks',reason='synthetic',telegram_reason_he='',telegram_news_he=[],relevant_news=[]),
        dict(ticker=ticker,company=ticker,atr=2,technical_score=7,combined_rank_score=.9,average_dollar_volume=1e9),
        dict(action='BUY',confidence=.91,news_relevance=.9,news_sentiment=.4),{},'isolated-image-test')


def state():
    with database.get_db_connection() as c:
        return {k:[dict(r) for r in c.execute(q)] for k,q in {
            'account':'SELECT cash,fees_paid,realized_pnl FROM scanner_accounts ORDER BY id',
            'trades':'SELECT id,remaining_quantity,fees,realized_pnl FROM scanner_trades ORDER BY id',
            'fills':'SELECT id,trade_id,quantity,price,fee FROM scanner_fills ORDER BY id',
            'reservation':"SELECT COALESCE(SUM(limit_price*quantity),0) amount FROM scanner_orders WHERE status IN ('pending','recovery_uncertain') AND purpose='entry'",
            'holds':"SELECT id,status,signal_id,limit_price,quantity FROM scanner_orders WHERE status='recovery_uncertain' ORDER BY id"}.items()}


def main(mode):
    if mode=='seed':
        migrations.migrate()
        with database.get_db_connection() as c:
            c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
        e.initialize_runtime();record('AAPL')
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET created_at='2026-01-05T14:30:00Z',valid_until='2026-01-05T15:30:00Z'")
        e.process_bar('AAPL',dict(at='2026-01-05T14:35:00Z',open=100,high=101,low=99,close=100))
        record('MSFT')
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET created_at='2026-01-05T14:40:00Z',valid_until='2026-01-05T14:50:00Z' WHERE status='pending'")
        ROOT.joinpath('before.json').write_text(json.dumps(state()))
    elif mode=='baseline':
        assert not state()['holds']
        e.initialize_runtime()
        assert state()==json.loads(ROOT.joinpath('before.json').read_text())
    elif mode=='create':
        assert hasattr(e,'_pending_recovery_check')
        now=datetime(2026,1,5,15,tzinfo=timezone.utc)
        with patch.object(e,'datetime',wraps=datetime) as clock,patch.object(e,'_bar_dicts',return_value=[]):
            clock.now.side_effect=lambda tz=None:now.astimezone(tz)
            e.monitor_prices()
        actual=state();before=json.loads(ROOT.joinpath('before.json').read_text())
        assert len(actual['holds'])==1
        assert all(actual[k]==before[k] for k in ('account','trades','fills','reservation'))
        ROOT.joinpath('held.json').write_text(json.dumps(actual))
    elif mode in ('rollback','restart','forward'):
        e.initialize_runtime()
        assert state()==json.loads(ROOT.joinpath('held.json').read_text())
        with patch.object(e,'_bar_dicts',return_value=[]):e.monitor_prices()
        assert record('MSFT')['status']=='DUPLICATE_BLOCKED'
        assert state()==json.loads(ROOT.joinpath('held.json').read_text())
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
        if mode=='rollback':
            assert not hasattr(e,'_pending_recovery_check')  # genuine compatibility image
            import recovery_state as r
            data=r.export_postgres(os.environ['DATABASE_URL'])
            assert len(data['hold_coverage']['order_ids'])==1
            subprocess.run(['age-keygen','-o',str(ROOT/'test-key')],capture_output=True,check=True)
            recipient=subprocess.check_output(['age-keygen','-y',str(ROOT/'test-key')]).decode().strip()
            encrypted,_=r.encrypted_bytes(data,recipient);(ROOT/'test.age').write_bytes(encrypted)
            assert r.decrypt(ROOT/'test.age',ROOT/'test-key')==data
    elif mode=='exit':
        before=state()
        bar=dict(at='2026-01-05T15:00:00Z',open=90,high=91,low=89,close=90)
        e.process_bar('AAPL',bar);after=state();e.process_bar('AAPL',bar)
        assert state()==after and len(after['fills'])>len(before['fills'])
        assert after['holds']==before['holds'] and after['reservation']==before['reservation']
        assert e.dashboard_payload()['lifecycle_verification']['accounting_ok']
    elif mode=='old_reader_rejects':
        import gzip,recovery_state as r
        data=json.loads(gzip.decompress(subprocess.check_output(['age','-d','-i',str(ROOT/'test-key'),str(ROOT/'test.age')])))
        try:r.validate(data)
        except ValueError:pass
        else:raise AssertionError('old_reader_accepted_v2')
    else:raise ValueError(mode)
    report={'phase':mode,'result':'PASS','build_sha':os.environ.get('BUILD_SHA')}
    with (ROOT/'results.jsonl').open('a') as out:out.write(json.dumps(report)+'\n')
    print(json.dumps(report))


with patch.object(requests.sessions.Session,'request',side_effect=AssertionError('external HTTP forbidden')), \
     patch('telegram_status.refresh_telegram_status_cards',return_value={}):
    main(sys.argv[1])
