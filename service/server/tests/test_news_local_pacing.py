"""Use a fake clock and relay; no generation or real sleeps."""
import pytest

import news_local_backoff
import news_local_pacing as pacing


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(pacing.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(pacing.time, 'sleep', sleep)
    monkeypatch.setattr(pacing, '_pacer', pacing.NewsPacer())
    return now, waits


def test_pacing_counts_failed_work_and_bounds_time_between_calls(clock, monkeypatch):
    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    now, waits = clock
    with pacing.slot():
        now[0] += 0.5
    with pytest.raises(ValueError), pacing.slot():
        now[0] += 6
        raise ValueError('fixture')
    with pacing.slot():
        now[0] += 45
    with pacing.slot():
        pass
    now[0] += 25
    with pacing.slot():
        pass
    assert waits == [3, 6, 12]


def test_news_scanner_and_trump_share_pacing_without_delaying_trade_translation(clock, monkeypatch):
    import ai_operations
    import ai_provider
    import ai_routing
    import trump_truth_translation

    monkeypatch.setenv('AI_TRADER_CLOUD', 'true')
    monkeypatch.setenv('AI_INFERENCE_MODE', 'ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED', 'false')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fixture')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL', 'fixture')
    monkeypatch.setattr(ai_routing, 'ready', lambda: True)
    now, waits = clock
    ledger = []
    starts = []

    def complete(*args):
        starts.append(now[0])
        now[0] += 4
        return {'ok': True}, {}

    monkeypatch.setattr(ai_routing, 'local_completion', complete)
    monkeypatch.setattr(ai_operations, 'record', lambda *args, **kwargs: ledger.append(now[0] - args[3]))
    token = news_local_backoff.begin_story()
    try:
        ai_provider.json_completion('fixture', {}, task='news')
        ai_provider.json_completion('fixture', {}, task='translation')
    finally:
        news_local_backoff.end_story(token)
    ai_provider.json_completion('fixture', {}, task='translation')
    trump_truth_translation.local_json('fixture', {}, {})
    assert starts == [100, 108, 112, 116]
    assert waits == [4]
    assert ledger == [4, 4, 4, 4]
