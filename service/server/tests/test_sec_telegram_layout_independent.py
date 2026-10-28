"""Independent synthetic public SEC wire checks; no real facts or sends."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock

import pytest
import requests

from test_sec_public_editorial import comparison

AT=datetime(2026,10,20,15,tzinfo=timezone.utc)
JOB=dict(accession='0000000001-26-000001',accepted_at=AT.isoformat(),form='10-K/A',
    tickers_json='["QAZZ"]',issuer_cik='0000000001',universe_snapshot_id='synthetic-universe')
CONTROLS=re.compile('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]')


@pytest.fixture
def sec(monkeypatch):
    import sec_intelligence as current
    import socket
    monkeypatch.setattr(socket,'create_connection',Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(requests.sessions.Session,'request',Mock(side_effect=AssertionError('HTTP forbidden')))
    monkeypatch.setenv('SEC_INTELLIGENCE_MATERIAL_CHANGE_PCT','10')
    monkeypatch.setenv('SEC_INTELLIGENCE_MATERIAL_MARGIN_PP','2')
    if os.getenv('SEC_LAYOUT_BASELINE')!='1':return current
    root=Path(__file__).resolve().parents[3]
    raw=subprocess.check_output(['git','-C',str(root),'show',
        '621d1981582b48e662f66a4ade5d93491dc39772:service/server/sec_intelligence.py'])
    old=types.ModuleType('qa_sec_layout_old');old.__file__=current.__file__
    exec(compile(raw,current.__file__,'exec'),old.__dict__)
    return old


def three_facts():
    # Deliberately unrelated synthetic company, quarter and amounts; not JBL.
    return [comparison('revenue',year=2025,value=1350000001.25,previous=1000000001.25),
        comparison('operating_income',year=2025,value=-75000000,previous=150000000),
        comparison('operating_cash_flow',year=2025,value=330000000,previous=220000000)]


def render(sec,facts=None):return sec._public_financial_text(JOB,dict(kind='financial',comparisons=facts or three_facts()))


def test_metric_heading_is_not_a_dense_value_period_and_commentary_line(sec):
    text=render(sec)
    headings=[line for line in text.splitlines() if line.startswith('• ')]
    assert len(headings)==3 and all(not re.search(r'\d|USD',line) for line in headings)


def test_final_wire_metric_blocks_remain_phone_length_and_idempotent(sec):
    from telegram_presentation import telegram_text,utf16_length
    wire=telegram_text(render(sec))
    assert max(utf16_length(line) for line in wire.splitlines())<=128
    assert wire==telegram_text(wire) and utf16_length(wire)<=4096


def test_rounded_change_is_explicitly_approximate_not_false_precision(sec):
    text=render(sec,[comparison('revenue',year=2025,value=120,previous=100)])
    assert 'כ־20.0%' in text


def test_values_units_periods_signs_and_selection_are_preserved_without_invention(sec):
    facts=three_facts();before=copy.deepcopy(facts);text=render(sec,facts)
    selected=sec._public_latest_material(JOB,facts)
    assert set(selected)=={'revenue','operating_income','operating_cash_flow'}
    for value in ('1,350,000,001.25','1,000,000,001.25','-75,000,000','150,000,000','330,000,000','220,000,000'):
        assert value+' USD' in text
    for date in ('2025-07-01','2025-09-30','2024-07-01','2024-09-30'):assert date in text
    assert '150.0%' in text and 'ירידה' in text
    assert facts==before and all(v not in text for v in ('JBL','Jabil','2026-08-31','המניה תעלה','מחיר יעד'))


@pytest.mark.parametrize('metric',['cash','current_debt','long_term_debt'])
def test_balance_cannot_create_operating_notice_or_displace_three_facts(sec,metric):
    balance=comparison(metric,year=2025,value=4000,previous=1000)
    assert render(sec,[balance]) is None
    text=render(sec,three_facts()+[balance])
    assert '4,000 USD' not in text and len([line for line in text.splitlines() if line.startswith('• ')])==3


def test_margin_percentage_points_not_growth_percent_and_balance_instant_basis(sec):
    margin=comparison('operating_margin',year=2025,value=15.25,previous=10)
    text=render(sec,[margin])
    assert '15.25%' in text and '10%' in text and '5.2' in text and 'נקודות אחוז' in text
    cash=comparison('cash',year=2025,value=3000,previous=1000)
    flow=comparison('operating_cash_flow',year=2025,value=120,previous=100)
    text=render(sec,[cash,flow])
    assert '3,000 USD' in text and '2025-09-30' in text and 'ליום' in text


def test_negative_margin_keeps_sign_and_downward_percentage_points_not_relative_growth(sec):
    fact=comparison('operating_margin',year=2025,value=-2.25,previous=3)
    text=render(sec,[fact])
    assert '-2.25%' in text and '3%' in text and 'ירידה של כ־5.2 נקודות אחוז' in text
    assert 'USD' not in text and '175.0%' not in text


@pytest.mark.parametrize('long_link',[False,True])
def test_actual_enqueue_and_mock_send_final_wire_keep_topic_correction_and_no_clipping(sec,monkeypatch,long_link):
    import scanner_engine,stock_scanner
    from telegram_presentation import utf16_length
    from telegram_topics import with_news_community_link
    link='https://t.me/'+('x'*480 if long_link else 'SyntheticCommunity')
    for key,value in dict(SEC_INTELLIGENCE_MODE='paper',SEC_INTELLIGENCE_KILL_SWITCH='false',
        STOCK_SCANNER_TELEGRAM_ENABLED='true',TELEGRAM_SEC_INTELLIGENCE_THREAD_ID='677',TELEGRAM_COMPANY_REPORTS_THREAD_ID='678',
        SEC_INTELLIGENCE_PUBLIC_NOT_BEFORE=(AT-timedelta(hours=1)).isoformat(),
        TELEGRAM_BOT_TOKEN='synthetic-bot',TELEGRAM_CHAT_ID='synthetic-public',
        TELEGRAM_COMMUNITY_URL=link).items():monkeypatch.setenv(key,value)
    class Conn:
        def execute(self,sql,args):
            assert sql=='SELECT members_json FROM si_universe_snapshots WHERE id=?'
            return Mock(fetchone=lambda:dict(members_json=json.dumps({'QAZZ':dict(company='North Star Instruments',issuer_cik=JOB['issuer_cik'])})))
        def cursor(self):return self
    queued=Mock(return_value=True);monkeypatch.setattr(scanner_engine,'enqueue_telegram',queued)
    evidence=dict(kind='financial',comparisons=three_facts());before=copy.deepcopy(evidence)
    assert sec._enqueue_material_public_alert(JOB,evidence,AT,Conn()) is True
    args=queued.call_args.args
    assert args[1]=='sec-intelligence:'+JOB['accession'] and args[2]=='sec_intelligence'
    message=args[3];assert 'תיקון לדיווח קודם' in message and 'QAZZ' in message and 'North Star Instruments' in message
    assert queued.call_args.kwargs['published_at']==JOB['accepted_at'] and evidence==before
    session=Mock();session.post.return_value=Mock(raise_for_status=lambda:None)
    monkeypatch.setattr(stock_scanner.requests,'Session',lambda:session)
    assert stock_scanner.send_telegram(message,{'telegram_enabled':True},'company_report')=='sent'
    wire=session.post.call_args.kwargs['data']['text'];visible=CONTROLS.sub('',wire)
    assert session.post.call_args.kwargs['data']['message_thread_id']==678
    assert utf16_length(wire)<=4096 and '…' not in wire
    assert all(v in visible for v in ('1,350,000,001.25 USD','-75,000,000 USD','330,000,000 USD',
        '2025-07-01','2024-09-30',link))
    assert with_news_community_link(with_news_community_link(message,'sec_intelligence'),'sec_intelligence')==with_news_community_link(message,'sec_intelligence')
    assert 'נקלט ב־SEC' in visible and '20/10/2026' in visible


def test_no_latest_valid_comparison_never_gains_notice_from_layout(sec):
    fact=comparison('revenue',year=2025,value=120,previous=100)
    fact.update(reason='no_comparable_prior',previous=None,change_pct=None)
    assert render(sec,[fact]) is None


@pytest.mark.parametrize('event',['entry','tp','stop','sell','stop_change'])
def test_trade_alerts_are_not_reformatted_by_sec_layout(sec,event):
    from telegram_topics import with_news_community_link
    raw='TP/SL fixture - no SEC layout, unchanged 123.45 USD'
    assert with_news_community_link(raw,event)==raw
