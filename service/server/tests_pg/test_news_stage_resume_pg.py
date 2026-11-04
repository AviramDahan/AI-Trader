"""Real isolated PostgreSQL checkpoint, mocked inference; never Production."""
from unittest.mock import Mock
import pytest


@pytest.mark.parametrize('source_stage,review_stage',[
    ('source_analysis','quality_review'),('public_translation','public_translation_review')])
def test_postgres_reuses_only_validated_exact_stage_after_failure(pg,monkeypatch,source_stage,review_stage):
    import jsonschema
    from database import get_db_connection
    from news_call_context import article,call
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    schema={'type':'object','properties':{'relevance':{'type':'number','minimum':0,'maximum':1}},
            'required':['relevance'],'additionalProperties':False}
    source=Mock(return_value={'relevance':.8})
    review=Mock(side_effect=TimeoutError('synthetic'))
    for _ in range(2):
        with article(42,'version-1','synthetic source'):
            assert call(source_stage,source,'prompt',{'source':'unchanged'},1000,schema=schema)=={'relevance':.8}
            with pytest.raises(TimeoutError):call(review_stage,review,'review',{},1000,schema=schema)
    assert source.call_count==1 and review.call_count==2
    with get_db_connection() as c:
        assert c.execute('SELECT count(*) AS n FROM news_review_cache').fetchone()['n']==1
    source.return_value={'relevance':90}
    with article(42,'version-2','changed source'),pytest.raises(jsonschema.ValidationError):
        call(source_stage,source,'prompt',{'source':'changed'},1000,schema=schema)
    with get_db_connection() as c:
        assert c.execute('SELECT count(*) AS n FROM news_review_cache').fetchone()['n']==1


def test_canonical_runtime_reuses_exact_stage_in_postgres(pg,monkeypatch):
    import ai_provider
    from news_events.runtime import completion
    monkeypatch.setenv('AI_INFERENCE_MODE','ollama_first')
    monkeypatch.setenv('AI_OPENROUTER_FALLBACK_ENABLED','false')
    model=Mock(return_value={'relevance':.8})
    monkeypatch.setattr(ai_provider,'json_completion',model)
    schema={'type':'object','properties':{'relevance':{'type':'number','minimum':0,'maximum':1}},
            'required':['relevance'],'additionalProperties':False}
    payload={'canonical_event_id':'synthetic','evidence_version':'v1'}
    assert completion('source_analysis','prompt',payload,schema)[0]=={'relevance':.8}
    value,usage=completion('source_analysis','prompt',payload,schema)
    assert value=={'relevance':.8} and usage['checkpoint_hit'] is True
    assert model.call_count==1
