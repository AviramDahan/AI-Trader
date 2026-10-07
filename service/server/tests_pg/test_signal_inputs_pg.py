"""Full application routes/readers on synthetic isolated PostgreSQL schemas."""
import sys
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import database
import final_ai
import signal_news
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_signal_inputs import NOW,seed_canonical
from test_signal_projection import seed_projection,accounting,isolated_client,assert_roundtrip


def test_pg_canonical_snapshot_reads_without_consuming_or_analyzing(pg,monkeypatch):
    from news_events.store import Store
    Store(database.get_db_connection,sandbox=True).install()
    with database.get_db_connection() as c:seed_canonical(c)
    original=database.get_db_connection;connections=[]
    def tracked():
        c=original();connections.append(c);return c
    monkeypatch.setattr(database,'get_db_connection',tracked)
    rows=signal_news.existing_news([dict(ticker='TEST',company='Synthetic Corporation')],72,NOW)
    assert rows['TEST'][0]['canonical_event_id']=='synthetic-event'
    with original() as c:
        assert c.execute('SELECT status,reason FROM ne_events').fetchone()['reason']=='low_importance'
        assert c.execute('SELECT count(*) n FROM ne_analysis').fetchone()['n']==0
    assert len(connections)==1


def test_pg_duplicate_concurrent_projection_posts_one_display_no_trade(pg,monkeypatch):
    payload=seed_projection();before=accounting();client=isolated_client(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post('/api/signals/strategy',
            headers={'Authorization':'Bearer synthetic'},json=payload),range(2)))
    assert all(r.status_code==200 for r in results),[r.text for r in results]
    assert results[0].json()['signal_id']==results[1].json()['signal_id']
    assert_roundtrip(client,payload)
    assert accounting()==before


def test_pg_decision_journal_concurrent_idempotency(pg,monkeypatch):
    monkeypatch.setenv('STOCK_SCANNER_FINAL_AI_PROVIDER','ollama')
    trace=final_ai.new_trace('synthetic','TEST',7)
    trace['decision']=dict(action='HOLD',confidence=.7,news_sentiment=0,news_relevance=.9,
        filter_failures=['ai_hold','ai_confidence_below_threshold'])
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(lambda _:final_ai.persist(trace),range(3)))
    with database.get_db_connection() as c:
        rows=c.execute("SELECT metrics_json FROM scanner_candidates WHERE stage='ai_decision'").fetchall()
        assert len(rows)==1 and json.loads(rows[0]['metrics_json'])['action']=='HOLD'
        assert c.execute('SELECT count(*) n FROM scanner_orders').fetchone()['n']==0
