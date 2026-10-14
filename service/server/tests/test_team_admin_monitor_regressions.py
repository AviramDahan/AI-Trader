"""Private health projection regression; synthetic databases and no probes."""
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
import admin_system_status as ops
import scanner_engine as engine
import test_scanner_engine as fixture
from test_admin_system_status import NOW


class TeamAdminProjectionTests(unittest.TestCase):
    tearDown = fixture.ScannerEngineTests.tearDown
    signal = fixture.ScannerEngineTests.signal
    candidate = fixture.ScannerEngineTests.candidate
    decision = fixture.ScannerEngineTests.decision

    def setUp(self):
        fixture.ScannerEngineTests.setUp(self)
        with database.get_db_connection() as c:
            c.execute('CREATE TABLE IF NOT EXISTS admin_alerts(dedupe_key TEXT PRIMARY KEY,message TEXT NOT NULL,status TEXT,created_at TEXT)')
            for key in ops.SERVICE_LIMITS:
                c.execute('''INSERT INTO scanner_service_status(component,status,last_attempt_at,last_success_at,detail)
                    VALUES(?,?,?,?,?) ON CONFLICT(component) DO UPDATE SET status=excluded.status,
                    last_attempt_at=excluded.last_attempt_at,last_success_at=excluded.last_success_at''',
                    (key, 'ok', NOW.isoformat(), NOW.isoformat(), 'synthetic'))
            values = {
                'ollama_connectivity_watch_v1': {'enabled': True, 'status': 'ready',
                    'last_check_at': NOW.isoformat(), 'active': False},
                'ai_cost_reconciliation': {'checked_at': NOW.isoformat(), 'remaining': 20, 'credit_balance': 2},
                'news_canonical_health': {'checked_at': NOW.isoformat(), 'queue_size': 0,
                    'oldest_queue_seconds': 0, 'alarms': []},
            }
            for key, value in values.items():
                c.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json''',
                    (key, json.dumps(value), NOW.isoformat()))

    def pending(self, ticker='IFF'):
        with patch.object(engine, 'now_z', return_value=(NOW-timedelta(minutes=10)).isoformat()):
            return engine.record_signal(self.signal(ticker=ticker), self.candidate(ticker),
                                        self.decision(), {}, 'synthetic-projection')

    def cursor(self, ticker, stamp):
        with database.get_db_connection() as c:
            c.execute("INSERT INTO scanner_price_cursors(ticker,last_bar_at,status) VALUES(?,?,'ok')", (ticker, stamp.isoformat()))

    def snapshot(self, roles=(11, 12, 13)):
        with database.get_db_connection() as c:
            if database.using_postgres():
                # Unique isolated test database only; release at connection close.
                for role in roles:
                    c.execute('SELECT pg_advisory_lock(719322,?)', (role,))
            with patch.object(engine, 'market_session_state', return_value={
                    'is_open': True, 'is_trading_day': True, 'reason': 'open'}):
                return {node['id']: node for node in ops.build(c, NOW)['nodes']}

    def test_pending_order_only_samples_its_linked_symbol_not_historical_cursors(self):
        self.pending()
        self.cursor('IFF', NOW-timedelta(minutes=10))
        self.cursor('OLD', NOW-timedelta(days=8))
        node = self.snapshot()['monitor']
        self.assertEqual([bar['ticker'] for bar in node['bars']], ['IFF'])
        self.assertEqual(node['state'], 'healthy')
        self.assertEqual(node['metrics']['sampled_cursors'], 1)

    def test_missing_required_active_cursor_is_not_silently_healthy(self):
        self.pending()
        node = self.snapshot()['monitor']
        self.assertEqual([bar['ticker'] for bar in node['bars']], ['IFF'])
        self.assertIsNone(node['bars'][0]['bar_started_at'])
        self.assertFalse(node['bars'][0]['fresh_regular_session'])
        self.assertEqual(node['reason'], 'completed_bars_not_fresh')

    def test_monitor_reported_failure_is_not_downgraded_by_stale_bars(self):
        self.pending()
        self.cursor('IFF', NOW-timedelta(days=2))
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_service_status SET status='error' WHERE component='monitor'")
        node = self.snapshot()['monitor']
        self.assertEqual((node['state'], node['reason']), ('failed', 'reported_error'))
        self.assertFalse(node['bars'][0]['fresh_regular_session'])

    def test_news_failure_is_not_downgraded_by_canonical_alarm(self):
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_service_status SET status='error' WHERE component='news_feed'")
            report = {'checked_at': NOW.isoformat(), 'queue_size': 1,
                      'oldest_queue_seconds': 600, 'alarms': ['synthetic_alarm']}
            c.execute("UPDATE scanner_settings SET value_json=? WHERE key='news_canonical_health'", (json.dumps(report),))
        node = self.snapshot()['news_feed']
        self.assertEqual((node['state'], node['reason']), ('failed', 'reported_error'))
        self.assertEqual(node['metrics']['queue'], 1)

    def test_telegram_failure_is_not_downgraded_by_delivery_backlog(self):
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_service_status SET status='error' WHERE component='telegram'")
            c.execute('INSERT INTO admin_alerts(dedupe_key,message,status,created_at) VALUES(?,?,?,?)',
                      ('synthetic-backlog', 'Synthetic private alert', 'pending', (NOW-timedelta(minutes=10)).isoformat()))
        node = self.snapshot()['telegram']
        self.assertEqual((node['state'], node['reason']), ('failed', 'reported_error'))
        self.assertEqual(node['metrics']['admin_delivery_queued'], 1)

    def test_terminal_orders_do_not_require_live_cursor(self):
        result = self.pending()
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET status='expired' WHERE signal_id=?", (result['id'],))
        self.cursor('IFF', NOW-timedelta(days=2))
        node = self.snapshot()['monitor']
        self.assertEqual(node['bars'], [])
        self.assertEqual(node['state'], 'healthy')
