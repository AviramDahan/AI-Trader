"""Synthetic paper executions only. No provider, AI or Telegram requests."""
import copy
import json
import unittest
from unittest.mock import patch, Mock

import pytest
import database
import scanner_engine as engine
import short_policy as policy
from scanner_targets import structure_plan
from test_scanner_engine import ScannerEngineTests


def zone(low, high):
    return dict(low=low, high=high, touches=1, pivots=[dict(price=low, date='2026-09-21', kind='swing_low', confirmed_at='2026-09-23T20:05:00Z')])


def plan():
    # Exactly the already-existing SELL geometry: three forward support zones,
    # SINGLE executes TP2, not a new nearest-support/V2 policy.
    base = structure_plan('SELL', 100, 1, [zone(97,97.5),zone(94.8,95),zone(91.8,92),zone(101.6,102)],2)
    return policy.wrap(base, '2026-09-25', '2026-09-28T13:30:00Z')


def record(ticker='SHORTTEST'):
    p=plan()
    s=dict(ticker=ticker,company='Synthetic',action='SHORT',entry=100,stop_loss=p['stop'],target_plan=p,
           confidence=.91,time_horizon='1-4 weeks',reason='Synthetic',relevant_news=[])
    with patch.dict('os.environ',STOCK_SCANNER_SHORT_ENABLED='true'), patch.object(engine,'now_z',return_value='2026-09-28T13:30:00Z'):
        return engine.record_signal(s,{},dict(action='SELL'),{},'synthetic-short')


def bar(minute=35, **kwargs):
    return dict(dict(at=f'2026-09-28T13:{minute}:00Z',open=100,high=100.5,low=99.5,close=100),**kwargs)


def test_contract_preserves_existing_sell_levels_and_single_tp2():
    p=plan(); old=structure_plan('SELL',100,1,[*p['zones'],p['stop_zone']],2)
    for field in old:
        assert p[field]==old[field]
    assert p['active_target']==p['targets'][1]==95.15
    assert policy.validate_fill(p,100)>2
    original=copy.deepcopy(p)
    for price in (99.5,101,102.5,95):
        with pytest.raises(ValueError):policy.validate_fill(p,price)
    assert p==original
    with pytest.raises(ValueError):policy.validate(p,action='BUY')


def test_creation_flag_defaults_off(monkeypatch):
    monkeypatch.delenv('STOCK_SCANNER_SHORT_ENABLED',raising=False)
    assert not policy.enabled()
    assert policy.scanner_action('SELL','SYNTH')=='SELL'


def test_existing_bearish_policy_failures_and_source_validation():
    for zones in ([zone(97,97.5),zone(101,102)],  # fewer than three forward zones
                  [zone(97,97.5),zone(95,95.1),zone(92,92.1)],  # no stop anchor
                  [zone(99,101),zone(97,98),zone(95,96),zone(102,103)]):
        with pytest.raises(ValueError):structure_plan('SELL',100,1,zones,2)
    p=plan()
    with pytest.raises(ValueError,match='uncompleted'):
        policy.wrap(p,'2026-09-29','2026-09-28T13:30:00Z')
    damaged=copy.deepcopy(p);damaged['zones'][0]['pivots'][0]['confirmed_at']='2026-09-30T20:05:00Z'
    with pytest.raises(ValueError,match='unconfirmed'):policy.validate(damaged)
    # Same second-target 2R boundary used by the existing SELL policy.
    zs=[zone(97,97.5),zone(94.9,95.35),zone(91.8,92),zone(101.6,102)]
    exact=structure_plan('SELL',100,1,zs,2)
    assert exact['rr'][1]==2
    zs[1]['high']=95.36
    with pytest.raises(ValueError,match='risk_reward'):structure_plan('SELL',100,1,zs,2)


def test_short_scanner_preserves_ai_decision_and_original_plan():
    import stock_scanner
    p=plan();base={k:v for k,v in p.items() if k not in {'policy_version','action','strategy','active_target','source_data_at','decided_at','shadow_comparison'}}
    candidate=dict(ticker='SYNTH',company='Synthetic',price_as_of='2026-09-25',atr_pct=2,average_dollar_volume=1e9)
    decision=dict(action='SELL',confidence=.91,time_horizon='1-4 weeks',reason='Synthetic',news_sentiment=-.8,news_relevance=.9)
    with patch.object(stock_scanner,'_candidate_target_plan',return_value=base), patch.object(policy,'scanner_action',return_value='SHORT'),patch.object(stock_scanner,'format_signal',return_value='Synthetic'):
        api=Mock(return_value={'signal_id':None})
        s=stock_scanner._paper_order(candidate,decision,[],(100,'2026-09-28T13:30:00Z'),{},dict(min_risk_reward=2),api)
    assert s['action']=='SHORT' and s['take_profit']==95.15
    assert decision['action']=='SELL'
    assert api.call_args.args==('POST','/signals/strategy')  # never the immediate-execution API


class TestAutomaticShort(unittest.TestCase):
    setUp,tearDown=ScannerEngineTests.setUp,ScannerEngineTests.tearDown
    fetchall=ScannerEngineTests.fetchall

    def test_disabled_creation_and_risk_block_never_activate_position(self):
        p=plan()
        s=dict(ticker='SYNTH',company='Synthetic',action='SHORT',entry=100,stop_loss=p['stop'],target_plan=p,confidence=.9,reason='Synthetic',time_horizon='days')
        with patch.dict('os.environ',STOCK_SCANNER_SHORT_ENABLED='false'):
            with pytest.raises(ValueError,match='disabled'):engine.record_signal(s,{}, {}, {},'synthetic')
        assert not self.fetchall('SELECT * FROM scanner_signals')
        with database.get_db_connection() as c:c.execute('UPDATE scanner_accounts SET cash=0')
        assert record()['status']=='RISK_BLOCKED'
        assert not self.fetchall('SELECT * FROM scanner_orders')
        assert not engine.dashboard_payload()['signals'][0]['position_activated']

    def test_actual_short_gap_does_not_consume_another_hold_reservation(self):
        record('SHORTTEST');record('RESERVED')
        with database.get_db_connection() as c:
            c.execute('UPDATE scanner_accounts SET cash=200.3')
            c.execute("UPDATE scanner_orders SET status='recovery_uncertain' WHERE signal_id=(SELECT id FROM scanner_signals WHERE ticker='RESERVED')")
            c.execute("UPDATE scanner_signals SET status='RECOVERY_UNCERTAIN' WHERE ticker='RESERVED'")
        # 100.4 is a valid structural fill, but requires more collateral than
        # remains available after the other 100-unit hold plus commission.
        engine.process_bar('SHORTTEST',bar(open=100.4,high=100.6,low=100.2,close=100.4))
        assert not self.fetchall('SELECT * FROM scanner_fills')
        assert self.fetchall("SELECT status FROM scanner_orders WHERE signal_id=(SELECT id FROM scanner_signals WHERE ticker='SHORTTEST')")[0]['status']=='risk_rejected'
        assert self.fetchall("SELECT sum(limit_price*quantity) n FROM scanner_orders WHERE status='recovery_uncertain'")[0]['n']==100

    def test_limit_touch_full_tp2_and_restart_no_duplicate(self):
        record()
        assert not self.fetchall('SELECT * FROM scanner_fills')
        engine.process_bar('SHORTTEST',bar(high=99.9,open=99.7,close=99.7))
        assert not self.fetchall('SELECT * FROM scanner_fills')
        engine.process_bar('SHORTTEST',bar(40))
        trades=self.fetchall('SELECT * FROM scanner_trades')
        assert len(trades)==1 and trades[0]['side']=='short' and not trades[0]['is_shadow']
        assert trades[0]['entry_price']>=100
        # Creation disabled / global STAGED selected cannot alter a saved contract.
        with patch.dict('os.environ',STOCK_SCANNER_SHORT_ENABLED='false',STOCK_SCANNER_EXIT_STRATEGY='staged'):
            engine.initialize_runtime()
            engine.process_bar('SHORTTEST',bar(45,open=96,high=96.5,low=95,close=95.2))
            engine.process_bar('SHORTTEST',bar(45,open=96,high=96.5,low=95,close=95.2))
        fills=self.fetchall('SELECT * FROM scanner_fills')
        assert len(fills)==2 and fills[1]['target_index']==2 and fills[1]['price']<=95.15
        t=self.fetchall('SELECT * FROM scanner_trades')[0]
        assert t['remaining_quantity']==0 and t['realized_pnl']==pytest.approx(4.85) and t['fees']==.5
        account=self.fetchall('SELECT * FROM scanner_accounts')[0]
        assert account['cash']==pytest.approx(account['initial_cash']+4.35)
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_entry_side_without_short_contract_fails_closed(self):
        s=ScannerEngineTests.signal(self)
        with patch.object(engine,'now_z',return_value='2026-09-28T13:30:00Z'):
            engine.record_signal(s,{}, {}, {},'synthetic')
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET side='sell' WHERE purpose='entry'")
        engine.process_bar('AAPL',bar())
        assert not self.fetchall('SELECT * FROM scanner_fills')
        assert self.fetchall('SELECT status FROM scanner_orders')[0]['status']=='invalid'

    def test_gap_stop_not_guaranteed_and_same_bar_stop_wins(self):
        record('GAP');record('BOTH');record('ENTRY')
        for ticker in ('GAP','BOTH'):engine.process_bar(ticker,bar())
        engine.process_bar('GAP',bar(40,open=110,high=112,low=108,close=109))
        engine.process_bar('BOTH',bar(40,open=100,high=103,low=94,close=100))
        engine.process_bar('ENTRY',bar(high=103,low=94))
        fills=self.fetchall("SELECT * FROM scanner_fills WHERE fill_type!='entry' ORDER BY id")
        assert [f['fill_type'] for f in fills]==['stop','stop','stop']
        assert fills[0]['price']>110 and fills[1]['price']>102.25
        assert all(f['gross_pnl']<0 for f in fills)
        assert engine.dashboard_payload()['lifecycle_verification']['accounting_ok']

    def test_unfinished_creation_expiry_and_limit_gap(self):
        record('EARLY');record('GAP');record('EXPIRE')
        with patch.object(engine,'now_z',return_value='2026-09-28T13:36:00Z'):
            engine.process_bar('EARLY',bar())
        assert not self.fetchall('SELECT * FROM scanner_price_cursors')
        engine.process_bar('EARLY',bar(29))
        engine.process_bar('GAP',bar(open=102,high=103,low=101,close=102))
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET valid_until='2026-09-28T13:37:00Z' WHERE signal_id=(SELECT id FROM scanner_signals WHERE ticker='EXPIRE')")
        engine.process_bar('EXPIRE',bar());engine.process_bar('EXPIRE',bar(40))
        assert not self.fetchall('SELECT * FROM scanner_fills')
        assert self.fetchall("SELECT status FROM scanner_orders WHERE signal_id=(SELECT id FROM scanner_signals WHERE ticker='EXPIRE')")[0]['status']=='expired'

    def test_hold_blocks_both_directions_survives_restart_and_no_later_fill(self):
        from datetime import datetime,timezone
        result=record()
        # Missing first regular-session bar makes the path indeterminate.
        engine._pending_recovery_check('SHORTTEST',[bar(40)],datetime(2026,9,28,13,50,tzinfo=timezone.utc))
        held=self.fetchall('SELECT * FROM scanner_orders')[0]
        assert held['status']=='recovery_uncertain'
        initial=self.fetchall('SELECT cash FROM scanner_accounts')[0]['cash']
        engine.initialize_runtime();engine.process_bar('SHORTTEST',bar(45))
        assert record()['status']=='DUPLICATE_BLOCKED'
        s=ScannerEngineTests.signal(self);s.update(ticker='SHORTTEST',signal_id=None)
        assert engine.record_signal(s,{}, {}, {}, 'synthetic')['status']=='DUPLICATE_BLOCKED'
        assert not self.fetchall('SELECT * FROM scanner_fills')
        assert self.fetchall('SELECT cash FROM scanner_accounts')[0]['cash']==initial
        assert engine.dashboard_payload()['recovery_holds']['reserved_entry_notional']==100

    def test_sell_on_short_is_not_cover_and_existing_long_still_closes(self):
        record();engine.process_bar('SHORTTEST',bar())
        with patch.dict('os.environ',STOCK_SCANNER_SHORT_ENABLED='true'):
            assert policy.scanner_action('SELL','SHORTTEST')=='SHORT'
            s=ScannerEngineTests.signal(self,action='SELL',ticker='SHORTTEST');s['signal_id']=None
            assert engine.record_signal(s,{}, {}, {},'synthetic')['status']=='BEARISH_ONLY'
            buy=ScannerEngineTests.signal(self);buy['signal_id']=None
            with patch.object(engine,'now_z',return_value='2026-09-28T13:30:00Z'):
                engine.record_signal(buy,{}, {}, {},'synthetic')
            engine.process_bar('AAPL',bar())
            assert policy.scanner_action('SELL','AAPL')=='SELL'
            sell=ScannerEngineTests.signal(self,action='SELL');sell['signal_id']=None
            assert engine.record_signal(sell,{}, {}, {},'synthetic')['status']=='PENDING_CLOSE'

    def test_short_display_direction_no_fake_shadow_and_render_only(self):
        record();engine.process_bar('SHORTTEST',bar())
        engine.process_bar('SHORTTEST',bar(40,open=98,high=99,low=97,close=98))
        data=engine.dashboard_payload();t=data['trades'][0]
        assert data['strategy_comparison']==[]
        assert t['unrealized_pnl']==2 and t['operational_tp2_pct']==1
        assert t['open_gross_pct']==2 and t['realized_net_pct']<0
        s=data['signals'][0]
        assert s['signal_eligibility']=='QUALIFIED' and s['active_target']==95.15
        msg=self.fetchall("SELECT message FROM scanner_telegram_outbox WHERE event_type='new_signal'")[0]['message']
        assert 'שורט' in msg and 'TP2' in msg and '100%' in msg and '$' not in msg
        assert len(msg.encode('utf-16-le'))//2<4000
        import telegram_status
        card=telegram_status.portfolio_status_message()
        assert 'Short' in card and '+2.00%' in card
        # Cash 99900-.25 plus short collateral value 102, not the 98 mark.
        assert telegram_status._account_pct(1.75 / 100000 * 100) in card
        signals=telegram_status.signals_status_message()
        assert 'שורט מדומה' in signals and '+2.00%' in signals
