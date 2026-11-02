"""Real disposable PostgreSQL with mocked model and no Telegram delivery."""
from dataclasses import replace
from unittest.mock import Mock
from test_news_events_runtime import live


def test_canonical_translation_routes_and_revalidates_without_ai_scores(live,monkeypatch):
    from news_events.analysis import CanonicalAnalyzer
    from news_events.runtime import queue_outbox,delivery_message,project
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    p,src,_,at,_=live
    src=replace(src,title='Federal Reserve interest rate decision',event_type='market',event_refs=(),
        source_excerpt='The Federal Reserve announced an interest rate decision at its scheduled press conference today.')
    eid=p.ingest(src,at)
    draft={'title_he':'הפדרל ריזרב פרסם החלטת ריבית','summary_he':'פורסמה החלטת הריבית.'}
    review={'faithful':True,'fluent_hebrew':True,'unsupported_claims':False,'duplicate_of':0,
            'material_new_fact':True,'explanation':'תקין'}
    assert p.analyze(eid,CanonicalAnalyzer(Mock(side_effect=[(draft,{}),(review,{})])),at)=='done'
    project(p,eid,at)
    assert queue_outbox(p,eid,at)==1
    with p.store.transaction() as c:
        news=c.execute('SELECT * FROM scanner_news').fetchone()
        assert news['analysis_status']=='public_translated' and news['relevance'] is None
        assert news['sentiment'] is None and news['interpretation_he'] is None
        sent=c.execute('SELECT * FROM scanner_telegram_outbox').fetchone()
        assert not c.execute('SELECT count(*) n FROM scanner_trades').fetchone()['n']
    assert delivery_message(dict(sent))
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','false')
    assert delivery_message(dict(sent)) is None


def test_legacy_translation_uses_null_scores_and_no_repeat_on_postgres(pg,monkeypatch):
    from datetime import datetime,timezone
    from database import get_db_connection
    import scanner_engine,news_pipeline
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    monkeypatch.setenv('STOCK_SCANNER_EXIT_STRATEGY','single')
    monkeypatch.setenv('NEWS_EVENTS_RUNTIME','false')
    monkeypatch.setenv('NEWS_EVIDENCE_ENABLED','false')
    with get_db_connection() as c:
        c.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','fixture',100000)")
    scanner_engine.initialize_runtime()
    at=datetime.now(timezone.utc)
    item={'provider':'federal_reserve','publisher':'fixture','title':'Federal Reserve announces rate decision',
          'url':'https://example.test/decision','published_at':at.isoformat(),
          'source_excerpt':'The Federal Reserve published its latest interest rate decision today.',
          'tickers':[],'scope':'market','source_kind':'headline_summary','headline_only':False}
    news_pipeline.ingest_items([item],at)
    analyzer=lambda rows:[dict(id=r['id'],title_he='פורסמה החלטת ריבית',summary_he='פורסמה החלטת הריבית.',
        _public_translation_only=True,duplicate_of=0) for r in rows]
    assert news_pipeline.analyze_news_jobs(analyzer=analyzer,at=at)['alerts']==1
    assert news_pipeline.analyze_news_jobs(analyzer=analyzer,at=at)['analyzed']==0
    with get_db_connection() as c:
        row=c.execute('SELECT * FROM scanner_news').fetchone()
        assert row['analysis_status']=='public_translated'
        assert all(row[k] is None for k in ('relevance','sentiment','materiality','interpretation_he'))
        assert c.execute('SELECT count(*) n FROM scanner_telegram_outbox').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM scanner_signals').fetchone()['n']==0
