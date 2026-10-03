import copy
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
import test_scanner_engine as fixture_module
import unittest
import scanner_engine as engine
import single_target_policy as policy


def zone(low, high):
    return dict(low=low, high=high, touches=1,
                pivots=[dict(price=low, date='2026-09-21', kind='swing_high', confirmed_at='2026-09-23T20:05:00+00:00')])


def plan(zones=None, entry=100, atr=1):
    return policy.build(entry, atr, zones or [zone(98, 98.4), zone(104.65, 105)],
                        '2026-09-25', '2026-09-28T13:30:00Z')


def test_one_target_exact_two_r_and_rounding_fail_closed():
    p = plan()
    assert p['targets'] == [104.5] and p['fractions'] == [1]
    assert p['rr'] == [2] and p['stop'] == 97.75
    with pytest.raises(ValueError, match='2r'):
        plan([zone(98, 98.4), zone(104.649, 105)])
    # Raw RR passes but rounded stop increases risk; rounded RR must also pass.
    with pytest.raises(ValueError, match='2r'):
        plan([zone(97.994, 98.4), zone(104.663, 105)])


@pytest.mark.parametrize('zones,reason', [
    ([zone(98,98.4),zone(102.4,102.6),zone(109,110)], '2r'),
    ([zone(99.9,100.1),zone(110,111)], 'inside'),
    ([zone(98,98.4)], 'no_forward'),
    ([zone(110,111)], 'no_structural'),
    ([zone(94,95),zone(115,116)], 'too_distant'),
])
def test_rejections(zones,reason):
    with pytest.raises(ValueError,match=reason):plan(zones)


def test_source_completion_and_future_confirmation():
    with pytest.raises(ValueError, match='uncompleted'):
        policy.build(100,1,[zone(98,98.4),zone(105,106)],'2026-09-28','2026-09-28T13:30:00Z')
    zs=[zone(98,98.4),zone(105,106)]
    zs[1]['pivots'][0]['confirmed_at']='2026-09-29T20:05:00Z'
    with pytest.raises(ValueError,match='unconfirmed'):plan(zs)


def test_fill_does_not_move_levels_or_accept_changed_rr():
    p=plan(); original=copy.deepcopy(p)
    assert policy.validate_fill(p,100)==2
    for price in (100.01,97,98.2,105):
        with pytest.raises(ValueError):policy.validate_fill(p,price)
    assert p==original
    with pytest.raises(ValueError):policy.validate(p, action='SELL')


def test_scanner_build_publication_and_sell_unchanged():
    import stock_scanner
    from unittest.mock import Mock
    c=dict(ticker='TEST',company='Synthetic',atr=1,price_as_of='2026-09-25',price_zones=[zone(98,98.4),zone(104.65,105)])
    with patch.object(engine,'lifecycle_settings',return_value={'active_strategy':'single'}):
        p=stock_scanner._candidate_target_plan(c,'BUY',100,{'min_risk_reward':2})
        assert p['policy_version']==policy.VERSION
        with patch.object(stock_scanner,'format_signal',return_value='synthetic'), patch.object(stock_scanner,'_candidate_target_plan',return_value=p):
            api=Mock(return_value={'signal_id':None})
            s=stock_scanner._paper_order(c,dict(action='BUY',confidence=.9,time_horizon='days',reason='synthetic'),[],(100,'2026-09-28T13:30:00Z'),{}, {'min_risk_reward':2},api)
        assert s['take_profit']==104.5 and s['risk_reward']==2
        with patch('scanner_targets.structure_plan',return_value={'v1':True}) as old:
            assert stock_scanner._candidate_target_plan(c,'SELL',100,{'min_risk_reward':2})=={'v1':True}
            old.assert_called_once()


def test_v2_can_reject_a_v1_pass_not_only_expand():
    from scanner_targets import structure_plan
    zs=[zone(98,98.4),zone(103,103.2),zone(106,106.2),zone(109,109.2)]
    assert len(structure_plan('BUY',100,1,zs,2)['targets'])==3
    with pytest.raises(ValueError,match='2r'):plan(zs)


def test_smci_historical_geometry_regression_not_a_current_signal():
    # Public historical levels only. Confirmation upper bound is the saved
    # completed-source cutoff, not a claimed exact historical pivot timestamp.
    zs=[zone(40.4500007629,41.5299987793),zone(42.3100013733,42.3100013733),zone(51.4000015259,51.4000015259)]
    p=plan(zs,entry=43.2599983215,atr=2.3242852347214287)
    assert p['stop']==39.77 and p['active_target']==51.05
    assert p['rr'][0]==pytest.approx(2.232093245)
    assert policy.validate_fill(p,43.53)>=2
    with pytest.raises(ValueError,match='rr'):policy.validate_fill(p,43.54)


def test_v2_source_provenance_does_not_reach_ai_payload():
    import stock_scanner
    c=dict(ticker='TEST',technical_direction='BUY',single_target_source={'private_to_executor':True},
           price_zones=[zone(98,98.4)])
    with patch('final_ai.review',return_value={}) as review:
        stock_scanner.ai_review(c,[],{})
    payload=json.loads(review.call_args.args[0][1]['content'])
    assert 'single_target_source' not in payload['candidate']
    assert 'confirmed_at' not in payload['candidate']['price_zones'][0]['pivots'][0]


def test_legacy_revision_tool_cannot_rewrite_v2_contract():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[3]/'scripts'/'revise_open_position_targets.py'
    spec=importlib.util.spec_from_file_location('isolated_target_revision',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    groups={1:[{'settings_json':json.dumps({'target_plan':plan()})}]}
    with patch.object(module,'_backup_sqlite') as backup:
        with pytest.raises(ValueError,match='immutable'):module._apply(groups,{},'synthetic')
        backup.assert_not_called()


class TestV2Lifecycle(unittest.TestCase):
    setUp, tearDown = fixture_module.ScannerEngineTests.setUp, fixture_module.ScannerEngineTests.tearDown
    signal = fixture_module.ScannerEngineTests.signal
    candidate = fixture_module.ScannerEngineTests.candidate
    decision = fixture_module.ScannerEngineTests.decision
    fetchall = fixture_module.ScannerEngineTests.fetchall
    def v2_record(self):
        signal=dict(self.signal(),signal_id=None,target_plan=plan(),stop_loss=97.75)
        with patch.object(engine,'now_z',return_value='2026-09-28T13:30:00Z'):
            return engine.record_signal(signal,self.candidate(),self.decision(),{},'synthetic-v2')

    def v2_bar(self,minute=35,**changes):
        return dict(at=f'2026-09-28T13:{minute:02}:00Z',open=100,high=101,low=99.5,close=100,**changes)

    def test_v2_full_exit_restart_and_presentation(self):
        self.v2_record()
        with patch.dict('os.environ', STOCK_SCANNER_EXIT_STRATEGY='staged'):
            engine.process_bar('AAPL',self.v2_bar())
        trades=self.fetchall('SELECT * FROM scanner_trades')
        self.assertEqual(len(trades),1)
        self.assertEqual((trades[0]['strategy'],trades[0]['tp1'],trades[0]['tp2'],trades[0]['tp3']),('single',104.5,None,None))
        payload=engine.dashboard_payload()
        self.assertEqual(payload['signals'][0]['operational_tp1_pct'],1)
        self.assertEqual(payload['signals'][0]['signal_eligibility'],'QUALIFIED')
        self.assertEqual(payload['strategy_comparison'],[])
        from telegram_status import _next_target
        self.assertEqual(_next_target(trades[0],set())[1],104.5)
        from position_charts import operational_allocations
        self.assertEqual(operational_allocations(trades[0]),[1.])
        message=self.fetchall("SELECT message FROM scanner_telegram_outbox WHERE event_type='new_signal'")[0]['message']
        self.assertIn('100%',message)
        self.assertNotIn('יעד 2',message)
        bar={**self.v2_bar(40),'open':104.5,'high':105,'low':104,'close':104.5}
        engine.process_bar('AAPL',bar)
        engine.initialize_runtime();engine.process_bar('AAPL',bar)
        self.assertEqual(len(self.fetchall('SELECT * FROM scanner_fills')),2)
        self.assertEqual(self.fetchall('SELECT remaining_quantity FROM scanner_trades')[0]['remaining_quantity'],0)
        self.assertTrue(engine.dashboard_payload()['lifecycle_verification']['accounting_ok'])

    def test_v2_incomplete_and_cross_creation_no_fill(self):
        self.v2_record()
        with patch.object(engine,'now_z',return_value='2026-09-28T13:36:00Z'):
            engine.process_bar('AAPL',self.v2_bar())
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.assertFalse(self.fetchall('SELECT * FROM scanner_price_cursors'))
        engine.process_bar('AAPL',self.v2_bar(29))
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))

    def test_v2_gap_stop_and_same_bar_ambiguity(self):
        self.v2_record();engine.process_bar('AAPL',self.v2_bar())
        engine.process_bar('AAPL',{**self.v2_bar(40),'open':100,'high':106,'low':97,'close':100})
        fills=self.fetchall("SELECT * FROM scanner_fills WHERE fill_type!='entry'")
        self.assertEqual([f['fill_type'] for f in fills],['stop'])
        self.assertLess(fills[0]['price'],97.75)

    def test_v2_gap_entry_is_not_manufactured(self):
        self.v2_record()
        engine.process_bar('AAPL',{**self.v2_bar(),'open':98.1,'high':100,'low':97.9,'close':99})
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'invalid')

    def test_v2_allocation_block_is_not_quality_rejection(self):
        import database
        with database.get_db_connection() as c:
            c.execute('UPDATE scanner_accounts SET cash=0')
        result=self.v2_record()
        self.assertEqual(result['status'],'RISK_BLOCKED')
        s=engine.dashboard_payload()['signals'][0]
        self.assertEqual(s['signal_eligibility'],'QUALIFIED')
        self.assertFalse(s['position_activated'])

    def test_v2_expiry_and_intrabar_expiry(self):
        self.v2_record()
        import database
        with database.get_db_connection() as c:
            c.execute("UPDATE scanner_orders SET valid_until='2026-09-28T13:37:00Z'")
        engine.process_bar('AAPL',self.v2_bar())
        self.assertFalse(self.fetchall('SELECT * FROM scanner_fills'))
        engine.process_bar('AAPL',self.v2_bar(40))
        self.assertEqual(self.fetchall('SELECT status FROM scanner_orders')[0]['status'],'expired')


# unittest discovers inherited tests too; retain them intentionally as V1/Legacy
# regression coverage against the same schema (no external services).
