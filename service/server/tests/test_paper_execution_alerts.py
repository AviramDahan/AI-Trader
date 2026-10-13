"""Synthetic lifecycle and wire format only. Never send to Telegram."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import test_scanner_engine as fixtures
import scanner_engine as engine
import database
from entry_rejection import CODES
from paper_execution_presentation import ENTRY_REASONS_HE, israel_time, order_update_lines, signal_state_lines
from telegram_presentation import telegram_text, utf16_length


def test_every_known_execution_reason_has_safe_hebrew_wording():
    assert set(ENTRY_REASONS_HE)==CODES
    for code in CODES:
        text='\n'.join(order_update_lines('invalid','BUY',code))
        assert ENTRY_REASONS_HE[code] in text and code not in text
        assert 'לא נפתחה פוזיציה' in text
    for value in (None,'private://secret','<script>private</script>',{},['secret']):
        assert 'private' not in '\n'.join(order_update_lines('invalid','BUY',value))


@pytest.mark.parametrize('status', ['PENDING_ENTRY','RISK_BLOCKED','DUPLICATE_BLOCKED','PENDING_CLOSE','HOLD','BEARISH_ONLY','UNKNOWN'])
def test_signal_state_is_plain_hebrew_not_a_raw_code_or_fill(status):
    text='\n'.join(signal_state_lines({'status':status}))
    assert status not in text and 'פוזיציה נפתחה: 100%' not in text
    wire=telegram_text(text)
    assert wire==telegram_text(wire) and wire.count('\u2066')==wire.count('\u2069')


def test_close_order_failure_does_not_claim_existing_position_disappeared():
    for status in ('invalid','risk_rejected','expired'):
        text='\n'.join(order_update_lines(status,'SELL'))
        assert 'אין להסיק שהפוזיציה נסגרה' in text
        assert 'לא נפתחה פוזיציה' not in text
    assert not order_update_lines('pending','BUY')
    assert not order_update_lines('filled','BUY')


def test_israel_display_requires_an_unambiguous_retained_timestamp():
    assert israel_time('2026-10-13T17:30:00Z')=='13/10/2026 20:30 (שעון ישראל)'
    assert 'חד־משמעי' in israel_time('2026-10-13T17:30:00')
    assert 'תקף' in israel_time(None)


class PaperExecutionAlertTests(unittest.TestCase):
    setUp=fixtures.ScannerEngineTests.setUp
    tearDown=fixtures.ScannerEngineTests.tearDown
    signal=fixtures.ScannerEngineTests.signal
    candidate=fixtures.ScannerEngineTests.candidate
    decision=fixtures.ScannerEngineTests.decision
    fetchall=fixtures.ScannerEngineTests.fetchall

    def record_v2(self):
        from test_single_target_v2 import plan
        s=self.signal(ticker='TEST');s.update(stop_loss=97.75,target_plan=plan())
        with patch('single_target_activation.enabled',return_value=True),patch.object(engine,'now_z',return_value='2026-09-28T13:30:00Z'):
            return engine.record_signal(s,self.candidate('TEST'),self.decision(),{},'synthetic-alert')

    def run_bar(self,opening):
        bar=dict(at='2026-09-28T13:35:00Z',open=opening,high=opening+.2,low=opening-.1,close=opening+.1)
        with patch.object(engine,'now_z',return_value='2026-09-28T14:00:00Z'):
            engine.process_bar('TEST',bar)
        return bar

    def updates(self):
        return self.fetchall("SELECT * FROM scanner_telegram_outbox WHERE dedupe_key LIKE 'order-status:%'")

    def test_real_policy_rejection_is_one_clear_alert_not_a_fill(self):
        self.record_v2()
        before=self.fetchall('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')
        bar=self.run_bar(99)  # A legal touched BUY limit, but stop distance fails.
        assert self.fetchall('SELECT status FROM scanner_signals')[0]['status']=='ENTRY_POLICY_REJECTED'
        assert not self.fetchall('SELECT * FROM scanner_fills') and not self.fetchall('SELECT * FROM scanner_trades')
        alerts=self.updates();assert len(alerts)==1
        assert 'מרחק הסטופ במחיר הביצוע' in alerts[0]['message']
        assert 'לא נפתחה פוזיציה חדשה' in alerts[0]['message']
        assert 'fill_stop_distance_invalid' not in alerts[0]['message'] and '$' not in alerts[0]['message']
        engine.initialize_runtime();engine.process_bar('TEST',bar)
        with database.get_db_connection() as c:
            engine._enqueue_order_execution_update(c.cursor(),self.fetchall('SELECT id FROM scanner_orders')[0]['id']);c.commit()
        assert len(self.updates())==1
        assert self.fetchall('SELECT cash,fees_paid,realized_pnl FROM scanner_accounts')==before

    def test_valid_fill_still_has_one_entry_alert_and_no_failure_alert(self):
        self.record_v2();self.run_bar(100)
        assert not self.updates()
        message=self.fetchall("SELECT message FROM scanner_telegram_outbox WHERE event_type='entry'")[0]['message']
        assert 'אירוע: כניסה בוצעה' in message and 'פוזיציית דמה פעילה' in message
        assert 'ממתין לכניסה' not in message and '$' not in message
        assert len(self.fetchall('SELECT * FROM scanner_trades WHERE is_shadow=0'))==1
        assert len(self.fetchall('SELECT * FROM scanner_fills'))==1

    def test_expiry_and_uncertainty_are_each_once_without_reservation_release(self):
        self.record_v2()
        before=self.fetchall('SELECT cash,fees_paid FROM scanner_accounts')
        engine._pending_recovery_check('TEST',[],datetime(2026,9,28,13,40,tzinfo=timezone.utc))
        assert 'חסום עד בירור' in self.updates()[0]['message']
        held=self.fetchall('SELECT status,quantity,limit_price FROM scanner_orders')
        assert held[0]['status']=='recovery_uncertain'
        engine.initialize_runtime();engine._expire_recovered_orders('TEST',datetime(2026,10,1,tzinfo=timezone.utc))
        assert len(self.updates())==1
        assert self.fetchall('SELECT status,quantity,limit_price FROM scanner_orders')==held
        assert self.fetchall('SELECT cash,fees_paid FROM scanner_accounts')==before
        assert not self.fetchall('SELECT * FROM scanner_fills')

    def test_expired_pending_order_alert_is_not_a_position_and_is_not_replayed(self):
        self.record_v2()
        when=datetime(2026,9,29,14,tzinfo=timezone.utc)
        engine._expire_recovered_orders('TEST',when)
        assert 'פג תוקף' in self.updates()[0]['message']
        assert 'לא נפתחה פוזיציה חדשה' in self.updates()[0]['message']
        engine.initialize_runtime();engine._expire_recovered_orders('TEST',when)
        assert len(self.updates())==1 and not self.fetchall('SELECT * FROM scanner_fills')

    def test_pending_signal_render_and_initialization_do_not_notify_old_failures(self):
        self.record_v2()
        text=self.fetchall("SELECT message FROM scanner_telegram_outbox WHERE event_type='new_signal'")[0]['message']
        assert 'סיגנל חדש, ממתין לכניסה' in text and 'טרם נפתחה מהסיגנל הזה' in text
        assert 'PENDING_ENTRY' not in text and '29/09/2026' in text
        assert utf16_length(text)<=4000 and text.count('\u2066')==text.count('\u2069')
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET status='invalid',plan_json=?",(json.dumps({'entry_rejection_reason':'fill_rr_below_2'}),));c.commit()
        engine.initialize_runtime()
        assert not self.updates()  # No all-history catch-up, scan or artificial send.

    def test_execution_update_uses_existing_outbox_once_with_mocked_sender(self):
        self.record_v2();self.run_bar(99)
        with patch.dict('os.environ',STOCK_SCANNER_TELEGRAM_ENABLED='true',STOCK_SCANNER_TELEGRAM_ENTRY_ALERTS='true'),patch('stock_scanner.send_telegram',return_value='sent') as send:
            engine.process_telegram_outbox();engine.process_telegram_outbox()
        calls=[c for c in send.call_args_list if c.args[2]=='signals_status']
        assert len(calls)==1 and 'מרחק הסטופ במחיר הביצוע' in calls[0].args[0]
        assert self.updates()[0]['status']=='sent' and self.updates()[0]['attempts']==1

    def test_execution_update_respects_existing_entry_alert_switch(self):
        self.record_v2();self.run_bar(99)
        with patch.dict('os.environ',STOCK_SCANNER_TELEGRAM_ENABLED='true',STOCK_SCANNER_TELEGRAM_ENTRY_ALERTS='false'),patch('stock_scanner.send_telegram',return_value='sent') as send:
            engine.process_telegram_outbox()
        assert not any(c.args[2]=='signals_status' for c in send.call_args_list)
        assert self.updates()[0]['status']=='disabled'
