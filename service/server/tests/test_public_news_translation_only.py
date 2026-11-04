"""Source-only public news path; isolated mocks, no providers or Telegram."""
import json
from unittest.mock import Mock
import pytest
from test_news_events import env as canonical_env, source as canonical_source, NOW


def test_public_market_translation_requests_no_market_analysis(monkeypatch):
    import news_quality as q
    import scanner_engine
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    monkeypatch.setattr(q,'recent_events',lambda row:[])
    outputs=[{'title_he':'החברה פרסמה דוח חדש','summary_he':'החברה פרסמה דוח חדש.'},
             {'faithful':True,'fluent_hebrew':True,'unsupported_claims':False,'explanation':'תקין'}]
    model=Mock(side_effect=outputs);monkeypatch.setattr(scanner_engine,'_ollama_json',model)
    row={'id':1,'scope':'market','title':'Company published a new report',
         'source_facts_json':json.dumps({'source_excerpt':'Company published a new report.'}),
         'verified_tickers_json':'[]','thesis':None}
    result=q.analyze_one(row)
    assert result['_public_translation_only'] is True
    assert set(result).isdisjoint({'relevance','sentiment','related','materiality','interpretation_he'})
    assert model.call_count==2
    assert set(model.call_args_list[0].kwargs['schema']['properties'])=={'title_he','summary_he'}


def test_public_translation_does_not_bypass_factual_checks(monkeypatch):
    import news_quality as q
    import scanner_engine
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    monkeypatch.setattr(q,'recent_events',lambda row:[])
    model=Mock(side_effect=[{'title_he':'מחיר 999','summary_he':'ידיעה בעברית'},
        {'faithful':True,'fluent_hebrew':True,'unsupported_claims':False,'explanation':'תקין'}])
    monkeypatch.setattr(scanner_engine,'_ollama_json',model)
    row={'id':1,'scope':'market','title':'Company published a new report',
         'source_facts_json':json.dumps({'source_excerpt':'Company published a new report.'}),
         'verified_tickers_json':'[]','thesis':None}
    with pytest.raises(ValueError,match='news_quality_rejected'):q.analyze_one(row)


def test_public_translation_rejects_extra_unrequested_analysis_fields(monkeypatch):
    import jsonschema,news_quality as q,scanner_engine
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    monkeypatch.setattr(scanner_engine,'_ollama_json',Mock(return_value={
        'title_he':'הודעה','summary_he':'פורסמה הודעה','relevance':1}))
    row={'id':1,'scope':'market','title':'Announcement','source_facts_json':'{}',
         'verified_tickers_json':'[]','thesis':None}
    with pytest.raises(jsonschema.ValidationError):q.analyze_one(row)


def test_position_or_verified_ticker_keeps_trade_analysis(monkeypatch):
    import news_quality as q
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    strict=Mock(return_value={'related':True});monkeypatch.setattr(q,'analyze_strict',strict)
    for row in ({'id':1,'scope':'open_position','thesis':'original'},
                {'id':2,'scope':'market','verified_tickers_json':'["AAPL"]'}):
        q.analyze_one(row)
    assert strict.call_count==2


@pytest.fixture
def isolated_pipeline(monkeypatch):
    from test_news_pipeline import NewsPipelineIntegrationTests
    case=NewsPipelineIntegrationTests(methodName='runTest');case.setUp()
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    yield case
    case.tearDown()


def test_public_translation_publishes_without_fabricating_scores_or_repeating(isolated_pipeline):
    import news_pipeline
    c=isolated_pipeline
    news_pipeline.ingest_items([c.item()],c.clock)
    analyzer=lambda rows:[dict(id=r['id'],title_he='החברה פרסמה עדכון',summary_he='פורסם עדכון',
                                _public_translation_only=True,duplicate_of=0) for r in rows]
    assert news_pipeline.analyze_news_jobs(analyzer=analyzer,at=c.clock)['alerts']==1
    row=c.rows('SELECT * FROM scanner_news')[0]
    assert row['analysis_status']=='public_translated'
    assert all(row[k] is None for k in ('relevance','sentiment','materiality','interpretation_he'))
    assert len(c.rows('SELECT * FROM scanner_telegram_outbox'))==1
    assert news_pipeline.analyze_news_jobs(analyzer=analyzer,at=c.clock)['analyzed']==0
    assert not c.rows('SELECT * FROM scanner_signals') and not c.rows('SELECT * FROM scanner_orders')


def test_scope_change_requeues_for_full_analysis(isolated_pipeline):
    import news_pipeline,database
    c=isolated_pipeline
    news_pipeline.ingest_items([c.item()],c.clock)
    def changed(rows):
        with database.get_db_connection() as db:
            db.execute("UPDATE scanner_news SET verified_tickers_json='[\"AAPL\"]' WHERE id=?",(rows[0]['id'],))
        return [dict(id=rows[0]['id'],title_he='עדכון',summary_he='ידיעה',_public_translation_only=True)]
    news_pipeline.analyze_news_jobs(analyzer=changed,at=c.clock)
    assert c.rows('SELECT status FROM scanner_news_jobs')[0]['status']=='retry'
    assert not c.rows('SELECT * FROM scanner_telegram_outbox')


def test_deduplication_includes_previously_published_public_translation(isolated_pipeline):
    import news_pipeline,news_quality
    c=isolated_pipeline
    first=c.item(url='https://example.test/first')
    news_pipeline.ingest_items([first],c.clock)
    analyzer=lambda rows:[dict(id=r['id'],title_he='החברה פרסמה עדכון',summary_he='פורסם עדכון',
                                _public_translation_only=True,duplicate_of=0) for r in rows]
    assert news_pipeline.analyze_news_jobs(analyzer=analyzer,at=c.clock)['alerts']==1
    second={**c.item(url='https://example.test/second'),'title':'Company reports meaningful change'}
    news_pipeline.ingest_items([second],c.clock)
    rows=c.rows('SELECT * FROM scanner_news ORDER BY id')
    assert len(rows)==2
    assert [r['id'] for r in news_quality.recent_events(rows[1])]==[rows[0]['id']]


def test_canonical_market_translation_uses_no_sentiment_and_routes_only_market(monkeypatch):
    from news_events.analysis import CanonicalAnalyzer
    from news_events.engine import route,Policy
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    event={'event_id':'synthetic','evidence_version':'v1','company_identity':None,
           'event_type':'market','tickers':[],'published_at':'2026-11-02T00:00:00Z',
           'title':'Company published a new report',
           'normalized_evidence':[{'text':'Company published a new report.'}], 'conflicts':[]}
    draft={'title_he':'החברה פרסמה דוח חדש','summary_he':'החברה פרסמה דוח חדש.'}
    review={'faithful':True,'fluent_hebrew':True,'unsupported_claims':False,
            'duplicate_of':0,'material_new_fact':True,'explanation':'תקין'}
    completion=Mock(side_effect=[(draft,{}),(review,{})])
    result=CanonicalAnalyzer(completion)(event)
    assert result.result=={**draft,'_public_translation_only':True}
    assert [c.args[0] for c in completion.call_args_list]==['public_translation','public_translation_review']
    assert route(event,result.result,[],[],{},Policy())==([('market_news',[])],None)
    assert route({**event,'tickers':['AAPL']},result.result,[],[],{},Policy())==([], 'translation_scope_changed')
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','false')
    assert route(event,result.result,[],[],{},Policy())==([], 'translation_scope_changed')


def test_canonical_translation_rejects_invented_numbers(monkeypatch):
    from news_events.analysis import CanonicalAnalyzer,AnalysisFailure
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    event={'event_id':'synthetic','evidence_version':'v1','company_identity':None,
           'event_type':'market','tickers':[],'published_at':'2026-11-02T00:00:00Z',
           'title':'Company published a new report',
           'normalized_evidence':[{'text':'Company published a new report.'}], 'conflicts':[]}
    completion=Mock(side_effect=[({'title_he':'מחיר 999','summary_he':'עדכון'},{}),
        ({'faithful':True,'fluent_hebrew':True,'unsupported_claims':False,'duplicate_of':0,
          'material_new_fact':True,'explanation':'תקין'}, {})])
    with pytest.raises(AnalysisFailure,match='news_quality_rejected'):
        CanonicalAnalyzer(completion)(event)


def test_canonical_pipeline_enforces_freshness_and_real_translation_shape(canonical_env,monkeypatch):
    from news_events.analysis import CanonicalAnalyzer
    from news_events.runtime import message
    p,store,_=canonical_env
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','true')
    item=canonical_source(title='Federal Reserve interest rates',event_type='market',event_refs=(),
        source_excerpt='The Federal Reserve announced its latest interest rate decision at a public scheduled press conference today.')
    eid=p.ingest(item,NOW)
    draft={'title_he':'הפדרל ריזרב פרסם החלטת ריבית','summary_he':'פורסמה החלטת הריבית של הפדרל ריזרב.'}
    review={'faithful':True,'fluent_hebrew':True,'unsupported_claims':False,'duplicate_of':0,
            'material_new_fact':True,'explanation':'תקין'}
    assert p.analyze(eid,CanonicalAnalyzer(Mock(side_effect=[(draft,{}),(review,{})])),NOW)=='done'
    preview=p.deliver_preview(eid,NOW)
    assert len(preview)==1 and preview[0]['topic']=='market_news'
    record=store.event(eid)
    body=message(record['body'],{**draft,'_public_translation_only':True},'market_news',[])
    assert 'משמעות אפשרית לסוחר' not in body
    full_result={**draft,'interpretation_he':'פרשנות פנימית למסחר'}
    assert 'פרשנות פנימית למסחר' not in message(record['body'],full_result,'market_news',[])
    assert 'פרשנות פנימית למסחר' in message(record['body'],full_result,'stock_news',['AAPL'])
    monkeypatch.setenv('STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED','false')
    assert p.deliver_preview(eid,NOW)==[]


def test_translation_usage_does_not_switch_existing_provider_or_model(monkeypatch):
    from news_events.runtime import completion
    client=Mock(return_value={'title_he':'ידיעה','summary_he':'עדכון'})
    monkeypatch.setattr('ai_provider.json_completion',client)
    payload={'source':{'canonical_event_id':'synthetic','evidence_version':'v1'}}
    for stage in ('public_translation','schema_repair:public_translation_review'):
        completion(stage,'prompt',payload,{'type':'object'})
        assert client.call_args.kwargs['task']=='news'
        assert client.call_args.kwargs['usage_task']=='translation'
