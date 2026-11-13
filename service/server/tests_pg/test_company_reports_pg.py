"""Actual isolated PG process/outbox checks; no Telegram, provider or AI calls."""
from test_sec_public_editorial_pg import seeded_public_process


def test_financial_notice_has_separate_route_without_second_outbox(pg, monkeypatch):
    rows = seeded_public_process(monkeypatch)
    assert len(rows) == 1
    assert rows[0]['event_type'] == 'sec_intelligence'
    assert rows[0]['dedupe_key'].startswith('sec-intelligence:')
    assert 'תוצאות פעילות החברה' in rows[0]['message']
    assert rows[0]['message'].count('תקופת הדיווח:') == 1
    assert '🔮 ציפיות האנליסטים\nלא זמין' in rows[0]['message']
    assert '📋 התוצאות בפועל' in rows[0]['message']
    assert '120 דולר' in rows[0]['message'] and 'מעל הצפי' not in rows[0]['message']
