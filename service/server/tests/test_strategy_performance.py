"""Synthetic retained records only; no providers, AI or Production."""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import entry_discovery
import strategy_performance as performance
from test_entry_strategies_integration import actual_detection
from test_entry_strategies_integration import (
    no_external_entry_io,
    test_each_real_discovery_signal_pending_fullbar_exit_restart as exercise_lifecycle,
)
from test_signal_inputs import db, clock

NOW = datetime(2026, 10, 7, 16, tzinfo=timezone.utc)
START = datetime(2026, 10, 5, 16, tzinfo=timezone.utc)
BURST = 'STOCKBEE_MOMENTUM_BURST'
RS = 'RELATIVE_STRENGTH_LEADER'


def package(ids=(BURST,)):
    records = [actual_detection(key)[0] for key in ids]
    return entry_discovery.attribution(records, records[0]['source_times']['decision_at'])


def baseline_package(direction='BUY'):
    record = dict(strategy_id='BASELINE', version='existing_trend_momentum_v1', state='DETECTED',
        direction=direction, score=.8, sourcehash='a'*64, evidence_ids=[],
        source_times=dict(decision_at='2026-10-06T14:00:37Z', source_observed_at='2026-10-06T14:00:35Z'),
        trigger={'kind':'existing_trend_momentum'})
    return entry_discovery.attribution([record], '2026-10-06T14:00:37Z')


def records(*, closed=False, price=110, ids=(BURST,), number=1):
    attribution = package(ids)
    stamp = '2026-10-06T14:05:00Z'
    technical = json.dumps({'entry_discovery': attribution, 'private_prompt': 'NEVER-EXPORT'})
    signal = dict(id=number, scan_id='synthetic', ticker=f'TEST{number}', action='BUY',
                  status='ACTIVE', created_at=stamp, legacy_unverified=0, technical_json=technical)
    order = dict(id=number, signal_id=number, purpose='entry', side='buy', status='filled',
                 created_at=stamp, valid_until='2026-10-07T14:05:00Z',
                 plan_json=json.dumps({'entry_discovery': attribution}))
    qty = 10 if closed else 5
    trade = dict(id=number, signal_id=number, order_id=number, ticker=signal['ticker'], side='long',
                 strategy='single', is_shadow=0, legacy_position_id=None,
                 status='closed' if closed else 'open', entry_price=100, original_quantity=10,
                 remaining_quantity=0 if closed else 5, original_r=5, original_stop=95,
                 current_stop=100, settings_json=json.dumps({'entry_discovery': attribution}),
                 realized_pnl=(price-100)*qty, fees=2, opened_at=stamp,
                 closed_at='2026-10-06T15:00:00Z' if closed else None,
                 last_price=104, last_bar_at='2026-10-06T14:10:00Z')
    fills = [dict(id=number*10, trade_id=number, order_id=number,
                  event_key=f'entry:{number}', fill_type='entry', price=100, quantity=10,
                  fee=1, gross_pnl=0, bar_at=stamp, created_at=stamp),
             dict(id=number*10+1, trade_id=number, order_id=number,
                  event_key=f'exit:{number}', fill_type='tp' if price>=100 else 'stop',
                  price=price, quantity=qty, fee=1, gross_pnl=(price-100)*qty,
                  bar_at='2026-10-06T15:00:00Z', created_at='2026-10-06T15:00:01Z')]
    return dict(signals=[signal], orders=[order], trades=[trade], fills=fills,
                discovery=[], technical=[], reviews=[], final=[], ai_decision=[])


def summarize(data, **kwargs):
    return performance.summarize(data, since=START, now=NOW, hours=48, **kwargs)


def route(result, key=BURST):
    return next(row for row in result['strategy_rows'] if row['strategy_id']==key)


def test_empty_no_closed_metrics_are_unknown_and_all_routes_visible():
    result = summarize({})
    assert len(result['strategy_rows']) == 7  # baseline, five, unattributed
    assert result['overall']['counts']['actual_entries'] == 0
    assert route(result)['metrics']['closed_win_rate'] is None
    assert route(result)['metrics']['profit_factor'] is None
    assert result['scope']['returns_are_portfolio_return'] is False


def test_partial_exit_and_fees_not_closed_or_full_position_return():
    result = summarize(records())
    row = route(result)
    assert row['counts']['actual_entries'] == row['counts']['open_trades'] == 1
    assert row['counts']['partial_exit_trades'] == 1
    assert row['counts']['fully_closed_trades'] == 0
    assert row['metrics']['closed_win_rate'] is None
    assert row['metrics']['open_realized_mean_net_pct'] == pytest.approx(4.8)
    assert row['metrics']['open_realized_mean_net_r'] == pytest.approx(.96)


def test_closed_win_loss_pf_and_expectancy_include_entry_and_exit_fees():
    win, loss = records(closed=True), records(closed=True, price=95, number=2)
    combined = {key:win[key]+loss[key] for key in win}
    row = route(summarize(combined))
    assert row['counts']['fully_closed_trades'] == row['metrics']['verified_closed'] == 2
    assert row['metrics']['closed_win_rate'] == .5
    assert row['metrics']['mean_closed_net_pct'] == pytest.approx(2.3)
    assert row['metrics']['expectancy_net_r'] == pytest.approx(.46)
    assert row['metrics']['profit_factor'] == pytest.approx(98/52)
    text = json.dumps(summarize(combined), allow_nan=False)
    assert 'NEVER-EXPORT' not in text and 'realized_pnl' not in text


def test_overlapping_detectors_count_one_global_trade_not_two_capital_accounts():
    result = summarize(records(closed=True, ids=(BURST, RS)))
    assert result['overall']['counts']['actual_entries'] == 1
    groups = result['exact_set_groups']
    assert len(groups) == 1 and groups[0]['counts']['actual_entries'] == 1
    assert route(result, BURST)['counts']['actual_entries'] == 1
    assert route(result, RS)['counts']['actual_entries'] == 1
    assert all(row['non_additive'] for row in result['strategy_rows'])


@pytest.mark.parametrize('damage', ['missing_attribution', 'order_mismatch', 'missing_fill', 'bad_fee', 'future_fill'])
def test_missing_or_inconsistent_evidence_never_becomes_profitable_zero(damage):
    data = records(closed=True)
    if damage=='missing_attribution':
        data['signals'][0]['technical_json']='{}'
        data['orders'][0]['plan_json']='{}'
        data['trades'][0]['settings_json']='{}'
    elif damage=='order_mismatch': data['orders'][0]['plan_json']='{}'
    elif damage=='missing_fill': data['fills'].pop(0)
    elif damage=='bad_fee': data['fills'][1]['fee']=100
    else: data['fills'][1]['created_at']='2026-10-08T15:00:00Z'
    result = summarize(data)
    assert route(result)['metrics']['closed_win_rate'] is None
    assert route(result)['metrics']['profit_factor'] is None
    assert result['coverage']['evidence_gaps']


def test_no_losses_pf_is_null_and_breakeven_is_real_zero_not_unknown():
    row = route(summarize(records(closed=True)))
    assert row['metrics']['profit_factor'] is None
    assert row['metrics']['profit_factor_status'] == 'UNDEFINED_NO_LOSSES'
    data=records(closed=True, price=100.2)
    data['trades'][0]['realized_pnl']=2
    data['fills'][1]['gross_pnl']=2
    row=route(summarize(data))
    assert row['metrics']['verified_closed']==1
    assert row['metrics']['mean_closed_net_pct']==0
    assert row['metrics']['expectancy_net_r']==0
    assert row['metrics']['breakeven']==1


def test_clipping_never_presents_complete_counts_or_metrics():
    result = summarize(records(closed=True), clipped=['fills'])
    assert result['coverage']['status']=='PARTIAL'
    assert route(result)['counts']['actual_entries'] is None
    assert route(result)['observed_counts']['actual_entries']==1
    assert route(result)['metrics']['closed_win_rate'] is None


def test_shadow_and_legacy_do_not_count_as_native_or_new_route_profit():
    data=records(closed=True)
    data['trades'][0]['is_shadow']=1
    result=summarize(data)
    assert result['overall']['counts']['actual_entries']==0
    assert result['excluded_cohorts']['Shadow']['trades']==1
    data['trades'][0]['is_shadow']=0
    data['trades'][0]['legacy_position_id']=99
    result=summarize(data)
    assert result['overall']['metrics']['verified_closed']==0
    assert result['excluded_cohorts']['Legacy']['trades']==1


def test_repeated_input_and_closing_sell_do_not_replace_entry_attribution():
    data=records(closed=True)
    data['signals'].append(dict(data['signals'][0],id=2,action='SELL',technical_json='{}'))
    data['fills'] += copy.deepcopy(data['fills'])
    result=summarize(data)
    assert result['overall']['counts']['signals']==1
    assert route(result)['metrics']['verified_closed']==1
    assert route(result)['metrics']['mean_closed_net_pct']==pytest.approx(9.8)


@pytest.mark.parametrize('short', [False, True])
def test_opposing_entry_order_side_never_verifies_profitable_history(short):
    data=records(closed=True, price=95 if short else 110)
    if short:
        source=baseline_package('SELL')
        data['signals'][0]['action']='SHORT'
        for row, field in ((data['signals'][0],'technical_json'),(data['orders'][0],'plan_json'),
                           (data['trades'][0],'settings_json')):
            row[field]=json.dumps({'entry_discovery':source})
        data['trades'][0].update(side='short',original_stop=105,realized_pnl=50)
        data['fills'][1]['gross_pnl']=50
        data['orders'][0]['side']='buy'
    else:
        data['orders'][0]['side']='sell'
    result=summarize(data)
    assert result['overall']['metrics']['verified_closed']==0
    assert result['overall']['counts']['actual_entries'] is None
    assert route(result)['metrics']['closed_win_rate'] is None


def test_valid_attributed_baseline_short_keeps_signed_fee_inclusive_net():
    data=records(closed=True, price=95)
    source=baseline_package('SELL')
    data['signals'][0]['action']='SHORT'
    data['orders'][0]['side']='sell'
    data['trades'][0].update(side='short',original_stop=105,realized_pnl=50)
    data['fills'][1]['gross_pnl']=50
    for row, field in ((data['signals'][0],'technical_json'),(data['orders'][0],'plan_json'),
                       (data['trades'][0],'settings_json')):
        row[field]=json.dumps({'entry_discovery':source})
    result=summarize(data)
    assert route(result,'BASELINE')['metrics']['verified_closed']==1
    assert route(result,'BASELINE')['metrics']['expectancy_net_r']==pytest.approx(.96)
    assert route(result,'BASELINE')['metrics']['mean_closed_net_pct']==pytest.approx(4.8)


def test_wrong_side_original_stop_is_not_valid_original_r_history():
    data=records(closed=True)
    data['trades'][0]['original_stop']=105
    result=summarize(data)
    assert result['overall']['metrics']['verified_closed']==0
    assert route(result)['metrics']['mean_closed_net_pct'] is None


def test_configuration_is_effective_server_flags_not_hardcoded_on(monkeypatch):
    for flag in entry_discovery.FLAGS.values(): monkeypatch.setenv(flag,'false')
    monkeypatch.setenv(entry_discovery.FLAGS[BURST],'true')
    result=summarize({})
    assert route(result)['enabled'] is True
    assert route(result,'PEAD')['enabled'] is False


@pytest.mark.parametrize('strategy_id', tuple(entry_discovery.FLAGS))
def test_actual_route_entry_exit_report_readonly_and_flags_do_not_rewrite_history(db, clock, monkeypatch, strategy_id):
    import database
    from datetime import timedelta
    exercise_lifecycle(None, clock, monkeypatch, strategy_id)
    for flag in entry_discovery.FLAGS.values():
        monkeypatch.setenv(flag, 'false')
    with database.get_db_connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY' if database.using_postgres()
                     else 'PRAGMA query_only=ON')
        before = [dict(row) for row in conn.execute('SELECT * FROM scanner_fills ORDER BY id')]
        result = performance.report(conn, 48, clock.instant+timedelta(seconds=1))
        repeated = performance.report(conn, 48, clock.instant+timedelta(seconds=1))
        assert result == repeated
        assert route(result, strategy_id)['enabled'] is False
        assert route(result, strategy_id)['counts']['actual_entries'] == 1
        assert route(result, strategy_id)['metrics']['verified_closed'] == 1
        assert route(result, strategy_id)['metrics']['mean_closed_net_pct'] is not None
        assert result['overall']['counts']['signals'] == 1
        assert result['overall']['counts']['fully_closed_trades'] == 1
        assert before == [dict(row) for row in conn.execute('SELECT * FROM scanner_fills ORDER BY id')]


def test_report_refuses_unprotected_snapshot(db):
    import database
    with database.get_db_connection() as conn:
        with pytest.raises(RuntimeError, match='read_only_snapshot_required'):
            performance.report(conn, 48, NOW)
