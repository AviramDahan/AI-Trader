"""Read-only PostgreSQL report over a consistent snapshot, no workers/network."""
from datetime import datetime, timezone
import json
import database
import signal_research


def test_pg_report_readonly_repeated_journal_and_null_outcomes(pg):
    from test_recovery_holds import initialize_empty
    initialize_empty()
    with database.get_db_connection() as c:
        for i in range(3):
            data=dict(phase='pre_ai',outcome='REJECT',action='BUY',policy_version='single_target_v2',
                      rejection_reason='no_forward_zone',quote=dict(price=100),observed_at='2026-10-07T14:00:00Z')
            c.execute('''INSERT INTO scanner_candidates(scan_id,ticker,company,stage,status,reason,metrics_json,created_at)
                VALUES(?, 'TEST','Synthetic','target_check','observed','no_forward_zone',?,'2026-10-07T14:00:00Z')''',(str(i),json.dumps(data)))
        c.commit()
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        r=signal_research.report(c,48,datetime(2026,10,7,16,tzinfo=timezone.utc))
        assert r['counts']['candidate_observations']==3 and r['counts']['unique_tickers']==1
        assert r['counts']['target_checked']==3 and r['counts']['target_pass']==0
        assert not r['outcomes'] and not r['clipped']
        assert c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only']=='on'
        assert c.execute('SELECT count(*) n FROM scanner_orders').fetchone()['n']==0


def test_pg_linked_fills_and_cohorts_match_full_application_accounting(pg):
    from unittest.mock import patch
    from test_recovery_holds import initialize_empty
    import scanner_engine
    initialize_empty()
    with patch.object(scanner_engine,'now_z',return_value='2026-10-07T13:30:00Z'):
        scanner_engine.record_signal(dict(ticker='TEST',company='Synthetic',action='BUY',entry=100,
            stop_loss=97,confidence=.9,time_horizon='days',reason='synthetic',relevant_news=[]),{},{},{},'synthetic')
    scanner_engine.process_bar('TEST',dict(at='2026-10-07T13:35:00Z',open=100,high=101,low=99,close=100))
    scanner_engine.process_bar('TEST',dict(at='2026-10-07T13:40:00Z',open=96,high=96,low=95,close=95.5))
    with database.get_db_connection() as c:
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        before=[dict(r) for r in c.execute('SELECT * FROM scanner_fills ORDER BY id')]
        r=signal_research.report(c,48,datetime(2026,10,7,16,tzinfo=timezone.utc))
        assert len(r['outcomes'])==2
        assert {o['cohort'] for o in r['outcomes']}=={'Native','Shadow'}
        assert all(o['evidence_status']=='VERIFIED_FILLS' and o['closed_net_r']<0 for o in r['outcomes'])
        assert before==[dict(row) for row in c.execute('SELECT * FROM scanner_fills ORDER BY id')]
