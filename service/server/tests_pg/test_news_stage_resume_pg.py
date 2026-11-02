"""Real isolated PostgreSQL checkpoint, mocked inference; never Production."""
from unittest.mock import Mock
import pytest


def test_postgres_reuses_only_validated_exact_stage_after_failure(pg,monkeypatch):
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
            assert call('source_analysis',source,'prompt',{'source':'unchanged'},1000,schema=schema)=={'relevance':.8}
            with pytest.raises(TimeoutError):call('quality_review',review,'review',{},1000,schema=schema)
    assert source.call_count==1 and review.call_count==2
    with get_db_connection() as c:
        assert c.execute('SELECT count(*) AS n FROM news_review_cache').fetchone()['n']==1
    source.return_value={'relevance':90}
    with article(42,'version-2','changed source'),pytest.raises(jsonschema.ValidationError):
        call('source_analysis',source,'prompt',{'source':'changed'},1000,schema=schema)
    with get_db_connection() as c:
        assert c.execute('SELECT count(*) AS n FROM news_review_cache').fetchone()['n']==1
