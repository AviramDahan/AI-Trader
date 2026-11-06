"""Independent lossless compact-presentation checks; synthetic sources only."""
import json

import pytest

from test_public_news_translation_only import isolated_pipeline


@pytest.fixture(autouse=True)
def no_external_work(monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, 'request',
                        lambda *_a, **_k: pytest.fail('No external HTTP in compact QA'))
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED', 'true')
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME', 'false')
    monkeypatch.setenv('AI_TRADER_CLOUD', 'false')
    monkeypatch.setenv('NEWS_EVIDENCE_ENABLED', 'false')


@pytest.mark.parametrize('title,summary,required', [
    ('UBS העלה את ההמלצה לקנייה', 'יעד המחיר הועלה מ־100 ל־120 דולר.',
     ['יעד המחיר', '100', '120']),
    ('מחיר היעד הועלה ל־150 דולר', 'העדכון בוצע על ידי UBS.', ['UBS', 'על ידי']),
    ('מחיר היעד של החברה הועלה', 'J.P. Morgan העלה את מחיר היעד מ־100 ל־120 דולר.',
     ['J.P. Morgan', '100', '120']),
    ('UBS הוריד את ההמלצה להחזק', 'יעד המחיר הופחת מ־150.50 ל־125.25 אירו.',
     ['150.50 ל־125.25', 'אירו', 'הופחת']),
    ('UBS עדכן את המלצתו', 'ההמלצה לא שונתה. יעד המחיר נותר 90 דולר.',
     ['לא שונתה', 'נותר 90']),
    ('UBS העלה מחיר יעד ל־$150', 'UBS העלה מחיר יעד ל־$1500.', ['$1500']),
    ('המלצה: Buy', 'המלצה: Buyback אינה דירוג המלצה.', ['Buyback', 'אינה']),
])
def test_complementary_facts_names_amounts_and_negations_are_not_filtered(title, summary, required):
    from news_analyst_presentation import compact_parts
    text = '\n\n'.join(compact_parts(title, summary, 'SYN'))
    for fact in required:
        assert fact in text


def test_empty_headline_preserves_existing_summary_without_new_inference():
    from news_analyst_presentation import compact_parts
    summary = 'J.P. Morgan הוריד יעד מחיר מ־150.50 ל־125.25 דולר. ההמלצה נשארה החזק.'
    text = '\n'.join(compact_parts(None, summary))
    assert summary in text


@pytest.mark.parametrize('topic,source,title,summary', [
    ('portfolio_watchlist', 'UBS raises Synthetic price target to $150 from $100',
     'UBS העלה את מחיר היעד', 'העדכון בוצע על ידי UBS. מחיר היעד הועלה מ־100 ל־150 דולר.'),
    ('important_stock_news', 'Example reports Q3 EPS $2.10; broker raises price target to $150',
     'החברה דיווחה על תוצאות הרבעון השלישי', 'הרווח למניה היה 2.10 דולר.'),
])
def test_personal_or_actual_reports_keep_exact_previous_presentation(monkeypatch, topic, source, title, summary):
    from news_events.runtime import message
    monkeypatch.setenv('TELEGRAM_COMPANY_REPORTS_RESULTS_ONLY_ENABLED', 'true')
    event = {'title': source, 'source_excerpt': '', 'published_at': '2026-11-06T14:00:00Z',
             'sources': [{'title': source, 'publisher': 'Synthetic Wire', 'raw_metadata': {}}]}
    result = {'title_he': title, 'summary_he': summary, 'interpretation_he': 'פרשנות קיימת ומסויגת.'}
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED', 'false')
    baseline = message(event, result, topic, ['SYN'])
    monkeypatch.setenv('TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED', 'true')
    assert message(event, result, topic, ['SYN']) == baseline


def test_legacy_general_queue_keeps_license_time_and_original_dedupe(isolated_pipeline):
    import news_pipeline
    case = isolated_pipeline
    original = {**case.item(provider='global_voices'),
                'title': 'UBS cuts Synthetic price target to $125 from $150',
                'source_excerpt': 'UBS lowered its stock price target from 150 dollars to 125 dollars.',
                'headline_only': False}
    news_pipeline.ingest_items([original], case.clock)
    before = case.rows('SELECT id,content_hash,source_facts_json FROM scanner_news')[0]
    summary = 'יעד המחיר הופחת מ־150 ל־125 דולר. העדכון בוצע על ידי UBS.'

    def translated(rows):
        return [dict(id=row['id'], title_he='UBS הוריד את מחיר היעד', summary_he=summary,
                     _public_translation_only=True, duplicate_of=0) for row in rows]

    assert news_pipeline.analyze_news_jobs(analyzer=translated, at=case.clock)['alerts'] == 1
    outbox = case.rows('SELECT * FROM scanner_telegram_outbox')[0]
    assert summary in outbox['message']
    assert 'CC BY 3.0' in outbox['message']
    assert 'https://creativecommons.org/licenses/by/3.0/' in outbox['message']
    assert 'פורסם:' in outbox['message']
    assert outbox['event_type'] == 'market_news'
    assert outbox['dedupe_key'] == f"market-news:{before['id']}:{before['content_hash']}"
    after = case.rows('SELECT content_hash,source_facts_json,relevance FROM scanner_news')[0]
    assert after['content_hash'] == before['content_hash']
    assert json.loads(after['source_facts_json']) == json.loads(before['source_facts_json'])
    assert after['relevance'] is None
    assert news_pipeline.analyze_news_jobs(analyzer=translated, at=case.clock)['analyzed'] == 0
    assert len(case.rows('SELECT * FROM scanner_telegram_outbox')) == 1
    assert not case.rows('SELECT * FROM scanner_signals')
    assert not case.rows('SELECT * FROM scanner_orders')
