"""Content-derived version10; old contracts and emergency overlay stay intact."""
import copy
from datetime import timedelta
import json
import pytest

import entry_discovery
import entry_intraday
import entry_strategy_execution as execution
import entry_window
import single_target_policy
import single_target_recovery as recovery
from test_entry_intraday import prior_case, witness_for, DECISION, OBSERVED, IDS
from test_entry_snapshot_versioning import data_for as old_packet
from test_emergency_snapshot_versioning import control, KEY, AT
from test_single_target_v2 import zone


def packet(strategy_id='VCP_BASE_CONTRACTION', *, baseline=False):
    frame,ctx=prior_case(strategy_id)
    setup=entry_intraday.prepare_setups(frame,decision_at=DECISION,
        source_observed_at=OBSERVED,enabled_ids=[strategy_id],context=ctx)[strategy_id]
    evidence,price,quote=witness_for(setup)
    record=entry_intraday.confirm_setup(setup,evidence,price=price,quote_at=quote,decision_at=DECISION)
    assert record['state']=='DETECTED',record
    records=[record]
    if baseline:
        old=copy.deepcopy(old_packet()['tables']['scanner_signals'][0])
        previous=json.loads(old['technical_json'])['entry_discovery']['detections'][0]
        previous.update(strategy_id='BASELINE',version='existing_trend_momentum_v1')
        previous['source_times']['decision_at']=DECISION.isoformat()
        previous['source_times']['source_observed_at']=OBSERVED.isoformat()
        records=[previous,record]
    package=entry_discovery.attribution(records,DECISION)
    until=(DECISION+timedelta(days=1)).isoformat()
    window=entry_window.build(DECISION,until)
    saved=execution.build(package,created_at=DECISION,valid_until=until,
        limit_price=price,quote_at=quote,entry_execution=window)
    plan=single_target_policy.build(price,1,[zone(price-3,price-2.8),zone(price+8,price+8.4)],
        '2026-10-02',DECISION.isoformat())
    attribution=dict(entry_discovery=package,target_plan=plan)
    if saved is not None:attribution['entry_strategy_execution']=saved
    order=dict(id=1,signal_id=1,purpose='entry',side='buy',order_type='limit',limit_price=price,
        created_at=DECISION.isoformat(),updated_at=DECISION.isoformat(),valid_until=until,status='pending',
        plan_json=json.dumps(dict(attribution,entry_execution=window,
            execution_settings=dict(active_strategy='single',entry_order_type='limit',
                slippage_bps=0,commission_per_share=.005,minimum_commission=.25))))
    signal=dict(id=1,action='BUY',planned_entry=price,original_stop=plan['stop'],
        tp1=plan['active_target'],tp2=None,tp3=None,tp1_pct=1,tp2_pct=0,tp3_pct=0,
        created_at=DECISION.isoformat(),valid_until=until,technical_json=json.dumps(attribution))
    return dict(version=10,created_at='2026-10-06T15:00:00Z',settings=[],
        tables=dict(scanner_signals=[signal],scanner_orders=[order],scanner_trades=[]))


@pytest.mark.parametrize('strategy_id',IDS)
def test_all_four_frozen_contracts_require10_and_validate_without_creation_flags(strategy_id):
    data=packet(strategy_id)
    assert recovery.version(data['tables'],[])==10
    recovery.validate_snapshot(data)
    for v in (2,7,8,9):
        with pytest.raises(ValueError,match='format_content_mismatch'):
            recovery.validate_snapshot(dict(data,version=v))


def test_emergency9_cannot_hide_new_format10_and_still_checks_its_future_clock():
    data=packet()
    data['settings']=[dict(key=KEY,value_json=json.dumps(control()),updated_at=AT)]
    assert recovery.version(data['tables'],data['settings'])==10
    recovery.validate_snapshot(data)
    with pytest.raises(ValueError,match='future_emergency_snapshot_control'):
        recovery.validate_snapshot(dict(data,created_at='2026-10-05T14:01:00Z'))


def test_mixed_baseline_audit_without_execution_also_requires10():
    data=packet(baseline=True)
    assert 'entry_strategy_execution' not in json.loads(data['tables']['scanner_signals'][0]['technical_json'])
    assert recovery.version(data['tables'])==10
    recovery.validate_snapshot(data)


def test_existing_version8_contract_is_not_rewritten_or_promoted():
    data=old_packet();before=copy.deepcopy(data)
    assert recovery.version(data['tables'])==8
    recovery.validate_snapshot(data)
    assert data==before
