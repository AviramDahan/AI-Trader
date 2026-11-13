"""Company report routing, readable copy and safe provisioning, synthetic only."""
import copy
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sec_intelligence as sec
from telegram_topics import thread_id_for_event, with_news_community_link
from test_sec_public_editorial import comparison, isolated, seeded_public_process


def test_financial_results_get_separate_outbox_and_readable_shared_period(isolated, monkeypatch):
    rows = seeded_public_process(monkeypatch)
    assert len(rows) == 1 and rows[0]['event_type'] == 'sec_intelligence'
    body = rows[0]['message']
    assert 'תוצאות פעילות החברה' in body and 'דיווח SEC מהותי' not in body
    assert 'מה זה אומר:' in body and 'לא לתחזיות האנליסטים' in body


def test_company_topic_has_no_sec_news_general_fallback(monkeypatch):
    for key in ('TELEGRAM_SEC_INTELLIGENCE_THREAD_ID', 'TELEGRAM_NEWS_THREAD_ID', 'TELEGRAM_TRADING_THREAD_ID'):
        monkeypatch.setenv(key, '123')
    for invalid in ('', '0', '-5', 'unknown'):
        monkeypatch.setenv('TELEGRAM_COMPANY_REPORTS_THREAD_ID', invalid)
        assert thread_id_for_event('company_report') is None
    monkeypatch.setenv('TELEGRAM_COMPANY_REPORTS_THREAD_ID', '456')
    assert thread_id_for_event('company_report') == 456
    assert thread_id_for_event('sec_intelligence') == 123


def test_report_sender_never_calls_network_without_topic(monkeypatch):
    import stock_scanner
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'fixture')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'fixture')
    monkeypatch.delenv('TELEGRAM_COMPANY_REPORTS_THREAD_ID', raising=False)
    monkeypatch.setattr(stock_scanner.requests, 'Session', Mock(side_effect=AssertionError('no send')))
    result = stock_scanner.send_telegram('fixture', {'telegram_enabled': True}, 'company_report')
    assert json.loads(result)['reason'] == 'company_reports_topic_not_configured'


def test_simple_copy_keeps_exact_values_signs_and_mixed_periods():
    job = {'accession': '0000000001-26-000001', 'accepted_at': '2026-10-28T12:00:00Z'}
    facts = [comparison(value=1_200_000_000, previous=1_000_000_000),
             comparison('operating_income', value=-50, previous=100)]
    before = copy.deepcopy(facts)
    full = sec._public_financial_text(job, {'comparisons': facts})
    short = sec._company_report_text(full)
    assert short.count('תקופת הדיווח:') == 1
    for value in ('1.2 מיליארד דולר', '1 מיליארד דולר', '-50 דולר', '150.0%', '2025-09-30'):
        assert value in short
    assert facts == before
    facts[1] = comparison('operating_income', year=2025, value=120, previous=100,
                          start_month='01-01', end_month='12-31')
    mixed = sec._company_report_text(sec._public_financial_text(job, {'comparisons': facts}))
    assert mixed.count('תקופת הדיווח:') == 2
    assert '2025-12-31' in mixed and '2026-09-30' in mixed


def test_company_news_hides_sources_and_keeps_invitation(monkeypatch):
    monkeypatch.setenv('TELEGRAM_COMMUNITY_URL', 'https://t.me/fixture')
    text = with_news_community_link('תוצאות\nמקור: https://example.invalid/', 'company_report')
    assert 'מקור:' not in text and 'example.invalid' not in text
    assert text.endswith('https://t.me/fixture')


@pytest.mark.parametrize('legacy', [False, True])
def test_actual_dispatch_preserves_once_only_receipt_and_routes_old_pending(isolated, monkeypatch, legacy):
    import scanner_engine, stock_scanner
    rows = seeded_public_process(monkeypatch)
    if legacy:
        with isolated() as conn:
            conn.execute("UPDATE scanner_telegram_outbox SET event_type='sec_intelligence'")
            conn.commit()
    sent = []
    monkeypatch.setattr(stock_scanner, 'send_telegram', lambda text, cfg, kind:
                        (sent.append(kind) or 'sent'))
    assert scanner_engine.process_telegram_outbox()['sent'] == 1
    assert sent == ['company_report']
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    with isolated() as conn:
        assert conn.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n'] == 1
        assert conn.execute('SELECT status FROM scanner_telegram_outbox').fetchone()['status'] == 'sent'


@pytest.mark.parametrize('control', ['kill', 'mode', 'topic'])
def test_report_dispatch_keeps_sec_safety_gates(isolated, monkeypatch, control):
    import scanner_engine, stock_scanner
    seeded_public_process(monkeypatch)
    if control == 'kill': monkeypatch.setenv('SEC_INTELLIGENCE_KILL_SWITCH', 'true')
    if control == 'mode': monkeypatch.setenv('SEC_INTELLIGENCE_MODE', 'off')
    if control == 'topic': monkeypatch.delenv('TELEGRAM_COMPANY_REPORTS_THREAD_ID')
    monkeypatch.setattr(stock_scanner, 'send_telegram', Mock(side_effect=AssertionError('no send')))
    assert scanner_engine.process_telegram_outbox()['sent'] == 0
    with isolated() as conn:
        assert conn.execute('SELECT status FROM scanner_telegram_outbox').fetchone()['status'] == 'cancelled'


def helper():
    path = Path(__file__).resolve().parents[3] / 'scripts/configure_company_reports_topic.py'
    spec = importlib.util.spec_from_file_location('company_topic_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_topic_creation_is_once_and_retry_reuses_verified_id(tmp_path):
    module = helper(); marker = tmp_path/'topic.json'
    call = Mock(return_value={'message_thread_id': 789})
    assert module.provision(call, marker) == 789
    assert call.call_args.args == ('createForumTopic',)
    assert module.provision(call, marker) == 789
    assert [c.args[0] for c in call.call_args_list] == ['createForumTopic', 'editForumTopic']


def test_ambiguous_creation_never_creates_again(tmp_path):
    module = helper(); marker = tmp_path/'topic.json'
    with pytest.raises(TimeoutError):
        module.provision(Mock(side_effect=TimeoutError), marker)
    call = Mock()
    with pytest.raises(RuntimeError, match='ambiguous_create'):
        module.provision(call, marker)
    call.assert_not_called()
