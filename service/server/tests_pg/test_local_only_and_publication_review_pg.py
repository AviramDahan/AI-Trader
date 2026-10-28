"""Disposable PostgreSQL; no live AI, Telegram or trades."""
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from test_news_events_runtime import live


def test_disabled_fallback_does_not_create_paid_usage_or_trades(pg,monkeypatch):
    import ai_routing,ai_provider,database
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.delenv('AI_OPENROUTER_FALLBACK_ENABLED',raising=False)
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic')
    monkeypatch.setenv('OPENROUTER_NEWS_MODEL','synthetic')
    monkeypatch.setattr(ai_routing,'ready',lambda:False)
    paid=Mock(side_effect=AssertionError('No paid completion'))
    monkeypatch.setattr(ai_provider.requests,'post',paid)
    with pytest.raises(ai_routing.LocalUnavailable):ai_provider.json_completion('synthetic',{})
    with pytest.raises(ai_routing.LocalUnavailable):ai_routing.check_available()
    paid.assert_not_called()
    with database.get_db_connection() as c:
        for table in ('scanner_orders','scanner_trades','scanner_signals','ai_call_usage'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0


def test_sent_market_paraphrase_is_not_requeued_after_restart(live):
    from news_events import runtime
    from news_events.analysis import CanonicalAnalyzer
    from news_events.engine import Analysis,Pipeline
    from news_events.publication_review import candidates
    from news_events.store import Store
    p,src,result,at,members=live
    original='RBNZ Governor Breman: panel reviewed fall in NZD, if persistent could boost imported inflation'
    item=replace(src,event_type='market',title=original,source_excerpt=original)
    first=p.ingest(item,at)
    result={**result,'title_he':'הבנק המרכזי דן בהיחלשות המטבע ובאינפלציית היבוא',
            'summary_he':'הוועדה בחנה את היחלשות הדולר הניו זילנדי; אם תימשך היא עלולה להגביר אינפלציית יבוא.'}
    assert p.analyze(first,lambda _:Analysis(result),at)=='done'
    assert runtime.queue_outbox(p,first,at)==1
    with p.store.transaction(True) as c:
        c.execute("UPDATE scanner_telegram_outbox SET status='sent',sent_at=?",(at.isoformat(),))
    paraphrase='Committee discussed decline in New Zealand dollar: if sustained could boost imported inflation'
    second=p.ingest(replace(item,source_id='two',url='https://example.org/article/54321',
                            title=paraphrase,source_excerpt=paraphrase),at)
    previous=candidates(p.store,p.store.event(second)['body'],at)
    assert len(previous)==1
    verdict=dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,
                 duplicate_of=previous[0]['id'],material_new_fact=False,
                 explanation='אותן עובדות בניסוח שונה.',scope_related=True)
    client=Mock(side_effect=[(result,{}),(verdict,{})])
    assert p.analyze(second,CanonicalAnalyzer(client,previous_publications=previous),at)=='done'
    assert runtime.queue_outbox(p,second,at)==0
    assert p.store.event(second)['reason']=='duplicate_publication'
    restarted=Pipeline(Store(p.store.connect,production=True),p.universe,lambda:members,not_before=p.not_before)
    assert restarted.queue(second,at)==[]
    assert client.call_count==2
    with p.store.transaction() as c:
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM ne_analysis WHERE status=\'done\'').fetchone()['n']==2
        for table in ('scanner_orders','scanner_trades','scanner_signals'):
            assert c.execute('SELECT count(*) n FROM '+table).fetchone()['n']==0
