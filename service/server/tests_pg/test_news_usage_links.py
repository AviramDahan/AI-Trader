import time
import pytest


def test_each_stage_and_transport_retry_links_one_existing_cost_row(pg, monkeypatch):
    from database import get_db_connection
    import ai_operations
    from news_call_context import article, call
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    body = {'id':'isolated-test', 'usage':{'prompt_tokens':100,'completion_tokens':20,'cost':.001}}
    with article(123, 'version-test', 'untrusted source facts'):
        for stage, retry in [('source_analysis',False),('quality_review',False),('editorial_repair',False),('editorial_repair',True)]:
            call(stage, ai_operations.record, 'news_analysis', 'unchanged-model', body,
                 time.monotonic(), True, retry=retry, notify_failure=False)
    with get_db_connection() as c:
        usage = c.execute('SELECT COUNT(*) n,SUM(actual_cost) cost FROM ai_call_usage').fetchone()
        linked = c.execute('''SELECT COUNT(*) n,SUM(u.actual_cost) cost FROM news_ai_call_links l
            JOIN ai_call_usage u ON u.call_id=l.call_id''').fetchone()
        repair = c.execute("SELECT COUNT(*) n FROM ai_call_usage WHERE task='retry_repair'").fetchone()
    assert usage['n'] == linked['n'] == 4
    assert float(usage['cost']) == pytest.approx(.004) == float(linked['cost'])
    assert repair['n'] == 1
