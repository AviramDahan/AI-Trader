"""Synthetic, isolated PostgreSQL + real age. Never production or external APIs."""
import copy,json,subprocess,uuid
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest,psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import config,database,migrations,scanner_engine as engine
import active_snapshot,recovery_state as recovery
from test_postgres_cloud import _sqlite_portfolio


def test_reservation_manifest_is_independent_of_source_row_order():
    from recovery_holds import coverage
    rows=[dict(id=i,status='recovery_uncertain',purpose='entry',quantity=1,limit_price=p)
          for i,p in enumerate((.1,.2,.3),1)]
    assert coverage(rows)==coverage(list(reversed(rows)))


def record(ticker,action='BUY'):
    signal=dict(signal_id=None,ticker=ticker,company=ticker,action=action,entry=100,stop_loss=97 if action=='BUY' else 103,
                confidence=.91,time_horizon='1-4 weeks',reason='synthetic',telegram_reason_he='',
                telegram_news_he=[],relevant_news=[])
    candidate=dict(ticker=ticker,company=ticker,technical_score=7,combined_rank_score=.92,atr=2,average_dollar_volume=1e9)
    return engine.record_signal(signal,candidate,dict(action=action,confidence=.91,news_relevance=.9,news_sentiment=.4),{},'isolated')


def initialize_empty():
    with database.get_db_connection() as c:
        c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
    engine.initialize_runtime()


def seed_legacy():
    """Synthetic original wallet, adopted through the real application path."""
    import scanner_legacy
    with database.get_db_connection() as c:
        agent=c.execute("SELECT id FROM agents WHERE name='us-stock-scanner'").fetchone()['id']
        c.execute("INSERT INTO positions(agent_id,symbol,market,side,quantity,entry_price,current_price,opened_at) VALUES(?,'TEST','us-stock','long',1,100,102,'2026-01-02T14:30:00Z')",(agent,))
        c.execute("INSERT INTO signals(signal_id,agent_id,message_type,market,signal_type,symbol,side,entry_price,quantity,timestamp,created_at,executed_at) VALUES(911,?,'operation','us-stock','realtime','TEST','buy',100,1,1,'2026-01-02T14:30:00Z','2026-01-02T14:30:00Z')",(agent,))
        tracked=dict(ticker='TEST',company='Synthetic Legacy',action='BUY',paper_execution='long_opened',entry=100,stop_loss=97,take_profit=106,paper_quantity=1,signal_id=911,status='OPEN')
        c.execute("INSERT INTO scanner_legacy_records(source,source_key,payload_json,imported_at) VALUES('stock-scanner.json','synthetic-911',?,'2026-01-05T14:30:00Z')",(json.dumps(tracked),))
    original_insert=scanner_legacy._insert
    def fixture_insert(cur,table,values):
        # Historical adoption was SQLite-only; PG does not expose lastrowid
        # for the position_id-keyed adoption table. Seed it without that adapter
        # return-value assumption, leaving application recovery code unmocked.
        if table=='scanner_legacy_adoptions':
            keys=list(values)
            cur.execute(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(values[k] for k in keys))
            return values['position_id']
        return original_insert(cur,table,values)
    with patch.object(engine,'now_z',return_value='2026-01-05T14:30:00Z'),patch.object(scanner_legacy,'_insert',side_effect=fixture_insert):
        assert len(scanner_legacy.adopt_positions()['adopted'])==1


def add_holds(tickers,action='BUY'):
    for ticker in tickers:
        result=record(ticker,action)
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET status='recovery_uncertain',created_at='2026-01-05T14:30:00Z',valid_until='2026-01-05T14:45:00Z' WHERE signal_id=?",(result['id'],))
            c.execute("UPDATE scanner_signals SET status='RECOVERY_UNCERTAIN' WHERE id=?",(result['id'],))


@contextmanager
def target_schema(pg):
    name='test_hold_restore_'+uuid.uuid4().hex
    with psycopg.connect(pg,autocommit=True) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    url=make_conninfo(pg,options='-c search_path='+name)
    try:
        with patch.object(config,'DATABASE_URL',url),patch.object(database,'DATABASE_URL',url):
            migrations.migrate()
            yield url
    finally:
        with psycopg.connect(pg,autocommit=True) as c:c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))


def state():
    with database.get_db_connection() as c:
        return {key:[dict(r) for r in c.execute(query)] for key,query in {
            'account':'SELECT cash,realized_pnl,fees_paid FROM scanner_accounts ORDER BY id',
            'legacy_wallet':'SELECT id,cash FROM agents ORDER BY id',
            'legacy_positions':'SELECT id,quantity,entry_price FROM positions ORDER BY id',
            'fills':'SELECT * FROM scanner_fills ORDER BY id',
            'trades':'SELECT id,remaining_quantity,fees,realized_pnl,current_stop FROM scanner_trades ORDER BY id',
            'holds':"SELECT * FROM scanner_orders WHERE status='recovery_uncertain' ORDER BY id",
            'reserved':"SELECT COALESCE(SUM(limit_price*quantity),0) amount FROM scanner_orders WHERE status IN ('pending','recovery_uncertain') AND purpose='entry'"}.items()}


@pytest.mark.parametrize('legacy',[False,True])
@pytest.mark.parametrize('native,tickers',[(False,['MSFT']),(True,['MSFT','NVDA']),(True,[])])
def test_hold_encrypted_roundtrip(pg,tmp_path,native,tickers,legacy):
    if native:
        source,last=_sqlite_portfolio(tmp_path)
        active_snapshot.import_data(active_snapshot.export_data(source),pg)
    else:
        initialize_empty()
    if legacy:seed_legacy()
    add_holds(tickers)
    before=state()
    data=recovery.export_postgres(pg)
    assert data['recovery_format']==data['version']==2
    assert len(data['hold_coverage']['order_ids'])==len(tickers)
    assert data['hold_coverage']['entry_reserved_notional']==before['reserved'][0]['amount']
    key=tmp_path/'test-identity'
    subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
    recipient=subprocess.check_output(['age-keygen','-y',str(key)]).decode().strip()
    encrypted,sizes=recovery.encrypted_bytes(data,recipient)
    artifact=tmp_path/'test.age';artifact.write_bytes(encrypted)
    decrypted=recovery.decrypt(artifact,key)
    assert decrypted==data
    with target_schema(pg) as target:
        recovery.restore(decrypted,target,'synthetic-scanner-token-32-characters')
        assert state()==before
        with database.get_db_connection() as c:
            assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==0
        engine.initialize_runtime()
        assert state()==before
        with patch.object(engine,'_bar_dicts',return_value=[]):engine.monitor_prices()
        assert state()==before  # expired original validity does not release the hold
        for ticker in tickers:assert record(ticker)['status']=='DUPLICATE_BLOCKED'
        assert state()==before
        after=recovery.export_postgres(target)
        assert after['hold_coverage']==data['hold_coverage']
        if legacy:
            with database.get_db_connection() as c:
                assert c.execute("SELECT count(*) n FROM scanner_orders WHERE status='imported' AND purpose='legacy_adoption'").fetchone()['n']==1
                assert c.execute('SELECT quantity FROM positions').fetchone()['quantity']==1
        if native:
            bar={**last,'at':(datetime.fromisoformat(last['at'])+timedelta(minutes=5)).isoformat(),
                 'open':90,'high':91,'low':89,'close':90}
            engine.process_bar('AAPL',bar)
            closed=state();engine.process_bar('AAPL',bar)
            assert state()==closed
            assert len(closed['fills'])>len(before['fills'])
            assert closed['holds']==before['holds']
            assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']
        unchanged=state()
        with pytest.raises(ValueError,match='already_imported'):recovery.restore(decrypted,target,'synthetic-scanner-token-32-characters')
        assert state()==unchanged
    print('HOLD_ROUNDTRIP_PASS '+json.dumps(dict(native=native,holds=len(tickers),**sizes)))


@pytest.mark.parametrize('damage',['purpose','type','position','adoption','signal','amount'])
def test_imported_parent_validation_fails_closed(pg,damage):
    initialize_empty();seed_legacy()
    data=recovery.export_postgres(pg)
    order=data['tables']['scanner_orders'][0]
    if damage=='purpose':order['purpose']='entry'
    if damage=='type':order['order_type']='limit'
    if damage=='position':data['tables']['positions']=[]
    if damage=='adoption':data['tables']['scanner_legacy_adoptions']=[]
    if damage=='signal':data['tables']['scanner_signals'][0]['legacy_unverified']=0
    if damage=='amount':order['quantity']+=1
    data.pop('snapshot_id');data['snapshot_id']=active_snapshot.digest(data)
    with target_schema(pg) as target:
        with pytest.raises(ValueError,match='invalid_imported_legacy_order'):
            recovery.restore(data,target,'synthetic-scanner-token-32-characters')
        with database.get_db_connection() as c:
            assert c.execute('SELECT count(*) n FROM agents').fetchone()['n']==0


@pytest.mark.parametrize('damage',['omit','parent','reservation','status','number','checksum'])
def test_hold_invalid_snapshot_no_partial_restore(pg,damage):
    initialize_empty();add_holds(['MSFT'])
    data=recovery.export_postgres(pg)
    if damage=='omit':data['tables']['scanner_orders']=[]
    if damage=='parent':data['tables']['scanner_signals']=[]
    if damage=='reservation':data['hold_coverage']['entry_reserved_notional']+=1
    if damage=='status':data['tables']['scanner_orders'][0]['status']='unknown'
    if damage=='number':data['tables']['scanner_orders'][0]['quantity']=-1
    if damage!='checksum':
        data.pop('snapshot_id');data['snapshot_id']=active_snapshot.digest(data)
    else:data['snapshot_id']='corrupt'
    with target_schema(pg) as target:
        with pytest.raises(ValueError):recovery.restore(data,target,'synthetic-scanner-token-32-characters')
        with database.get_db_connection() as c:
            assert c.execute('SELECT count(*) n FROM agents').fetchone()['n']==0
            assert c.execute('SELECT count(*) n FROM scanner_orders').fetchone()['n']==0


def test_legacy_coverage_unknown_and_nonempty_restore_refused(pg):
    initialize_empty();data=recovery.export_postgres(pg)
    old=copy.deepcopy(data);old['version']=old['recovery_format']=1;old.pop('hold_coverage');old.pop('snapshot_id')
    old['snapshot_id']=active_snapshot.digest(old)
    recovery.validate(old)  # readable, not evidence of absent holds
    with pytest.raises(ValueError,match='legacy_hold_coverage_unknown'):recovery.restore(old,pg,'synthetic-scanner-token-32-characters')
    before=state()
    with pytest.raises(ValueError,match='destination_not_empty'):recovery.restore(data,pg,'synthetic-scanner-token-32-characters')
    assert state()==before


def test_blocked_close_survives_natural_stop_without_recreating_position(pg,tmp_path):
    source,last=_sqlite_portfolio(tmp_path)
    active_snapshot.import_data(active_snapshot.export_data(source),pg)
    add_holds(['AAPL'],'SELL')
    bar={**last,'at':(datetime.fromisoformat(last['at'])+timedelta(minutes=5)).isoformat(),
         'open':90,'high':91,'low':89,'close':90}
    engine.process_bar('AAPL',bar)
    data=recovery.export_postgres(pg)
    assert len(data['hold_coverage']['order_ids'])==1
    assert data['hold_coverage']['entry_reserved_notional']==0
    assert not data['tables']['scanner_trades']
    with target_schema(pg) as target:
        recovery.restore(data,target,'synthetic-scanner-token-32-characters')
        engine.initialize_runtime()
        with patch.object(engine,'_bar_dicts',return_value=[]):engine.monitor_prices()
        assert state()['holds'] and not state()['trades'] and not state()['fills']
        assert recovery.export_postgres(target)['hold_coverage']==data['hold_coverage']
