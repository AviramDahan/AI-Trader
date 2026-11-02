"""Offline only: isolated SQLite and synthetic completions, no native AI."""
import json
import sqlite3
from unittest.mock import Mock
import pytest
import jsonschema
import news_quality
import scanner_engine
from news_call_context import article, call
from retry_policy import validation_detail

SCHEMA={'type':'object','properties':{'relevance':{'type':'number','minimum':0,'maximum':1}},'required':['relevance']}

@pytest.fixture
def cache(tmp_path,monkeypatch):
    path=tmp_path/'isolated.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE news_review_cache(cache_key TEXT PRIMARY KEY,content_version TEXT,result_json TEXT,created_at TEXT)')
    def connect():
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    monkeypatch.setattr('database.get_db_connection',connect)
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('AI_TRADER_CLOUD','true')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    return connect

def test_completed_source_survives_later_review_failure_and_restart(cache):
    source=Mock(return_value={'relevance':.7})
    review=Mock(side_effect=TimeoutError('synthetic'))
    for _ in range(2):
        with article(1,'version','source'):
            assert call('source_analysis',source,'source only',{'facts':'same'},1000,schema=SCHEMA)=={'relevance':.7}
            with pytest.raises(TimeoutError):call('quality_review',review,'review',{},1000,schema=SCHEMA)
    assert source.call_count==1 and review.call_count==2

def test_source_prompt_schema_and_model_changes_invalidate_cache(cache,monkeypatch):
    source=Mock(return_value={'relevance':.7})
    with article(1,'v1','source'):
        for facts in ('first','second'):
            call('source_analysis',source,'prompt',{'facts':facts},1000,schema=SCHEMA)
        call('source_analysis',source,'changed prompt',{'facts':'second'},1000,schema=SCHEMA)
        monkeypatch.setenv('OLLAMA_NEWS_MODEL','changed')
        call('source_analysis',source,'changed prompt',{'facts':'second'},1000,schema=SCHEMA)
    assert source.call_count==4

def test_invalid_results_never_saved_or_coerced(cache):
    source=Mock(return_value={'relevance':90})
    for _ in range(2):
        with article(1,'v','source'),pytest.raises(jsonschema.ValidationError):
            call('source_analysis',source,'prompt',{},1000,schema=SCHEMA)
    with cache() as c:assert c.execute('SELECT count(*) FROM news_review_cache').fetchone()[0]==0

def test_maximum_diagnostic_identifies_trusted_field_without_value():
    try:jsonschema.validate({'relevance':90},SCHEMA)
    except jsonschema.ValidationError as e:detail=json.loads(validation_detail(e,schema=SCHEMA))
    assert detail['schema_field']=='relevance' and len(detail['schema_sha256'])==64
    assert '90' not in detail.values()

def test_actual_strict_chain_resumes_only_completed_steps(cache,monkeypatch):
    import news_quality as q
    import scanner_engine
    counts={'source':0,'review':0,'dedup':0}
    result=dict(related=True,title_he='החברה פרסמה את תוצאותיה',summary_he='החברה פרסמה תוצאות כספיות.',
        interpretation_he='המשמעות אינה ודאית.',sentiment='neutral',materiality='low',relevance=.5)
    def generate(system,payload,predict,**kwargs):
        if 'draft' in payload:
            counts['review']+=1
            return dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,
                        duplicate_of=0,material_new_fact=True,explanation='תקין')
        if 'previous_sources' in payload:
            counts['dedup']+=1
            if counts['dedup']==1:raise TimeoutError('synthetic')
            return dict(duplicate_of=0,material_new_fact=True)
        counts['source']+=1
        return result
    monkeypatch.setattr(scanner_engine,'_ollama_json',generate)
    monkeypatch.setattr(q,'record_quality_check',lambda *a:None)
    monkeypatch.setattr(q,'recent_events',lambda row:[dict(id=2,title='Other company report',source_facts_json='{}')])
    monkeypatch.setenv('STOCK_SCANNER_NEWS_FAST_MARKET','false')
    row=dict(id=1,title='Company reports earnings',scope='market',published_at='2026-11-02T00:00:00Z',
             source_facts_json='{"source_excerpt":"Company reported earnings with no additional figures."}')
    with pytest.raises(TimeoutError):q.analyze_one(row)
    assert q.analyze_one(row)['duplicate_of']==0
    assert counts==dict(source=1,review=1,dedup=2)


def test_canonical_completion_resumes_completed_source_without_second_model_call(cache,monkeypatch):
    from news_events.runtime import completion
    import ai_provider
    source={'canonical_event_id':'synthetic-event','evidence_version':'v1'}
    model=Mock(return_value={'relevance':.7})
    monkeypatch.setattr(ai_provider,'json_completion',model)
    first,first_usage=completion('source_analysis','prompt',source,SCHEMA)
    second,second_usage=completion('source_analysis','prompt',source,SCHEMA)
    assert first==second=={'relevance':.7}
    assert model.call_count==1
    assert second_usage.get('checkpoint_hit') is True
    assert first_usage.get('checkpoint_hit') is not True


def test_canonical_pipeline_retries_failed_review_without_repeating_source_or_usage(cache,monkeypatch):
    from news_events.runtime import completion
    from news_events.analysis import CanonicalAnalyzer,AnalysisFailure
    import ai_provider
    event={'event_id':'fixture','evidence_version':'v1','company_identity':None,
           'event_type':'market','tickers':[],'published_at':'2026-11-02T00:00:00Z',
           'title':'Company published a new report',
           'normalized_evidence':[{'text':'Company published a new report.'}],'conflicts':[]}
    draft=dict(related=True,title_he='החברה פרסמה דוח חדש',summary_he='החברה פרסמה דוח חדש.',
               interpretation_he='המשמעות אינה ודאית.',sentiment='neutral',materiality='low',relevance=.5)
    review=dict(faithful=True,fluent_hebrew=True,unsupported_claims=False,duplicate_of=0,
                material_new_fact=True,explanation='תקין',scope_related=True)
    model=Mock(side_effect=[draft,TimeoutError('synthetic'),review])
    monkeypatch.setattr(ai_provider,'json_completion',model)
    analyzer=CanonicalAnalyzer(completion)
    with pytest.raises(AnalysisFailure):analyzer(event)
    completed=analyzer(event)
    assert model.call_count==3
    assert completed.result==draft
    assert [call['stage'] for call in completed.calls]==['quality_review']
