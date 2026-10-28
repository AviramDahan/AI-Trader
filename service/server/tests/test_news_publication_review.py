"""Retained publication dedupe; all model verdicts and transports synthetic."""
from dataclasses import replace
from datetime import timedelta
import json
from unittest.mock import Mock

import pytest

from news_events.analysis import CanonicalAnalyzer, AnalysisFailure
from news_events.engine import Analysis, Pipeline
from news_events.publication_review import candidates, duplicate_reference
from news_events.store import Store
from test_news_events import env, NOW, RESULT, source
from test_news_market_scope_independent import event, draft, review


def previous(text=None, **changes):
    return dict(id=42,event_id='a'*32,version='b'*64,sent_at=NOW.isoformat(),published_at=NOW.isoformat(),
                evidence=text or event()['normalized_evidence'][0]['text'],
                published_text='הבנק מסר שהריבית עשויה לעלות אם האינפלציה תימשך; לא הוכרזה החלטה.',
                **changes)


def test_paraphrase_review_uses_previous_only_in_editor_and_retains_source_result():
    prior=previous()
    client=Mock(side_effect=[(draft(),{}),(review(True,duplicate_of=42),{})])
    output=CanonicalAnalyzer(client,previous_publications=[prior])(event())
    assert output.result==draft() and output.publication_duplicate['id']==42
    assert client.call_count==2
    assert 'previous_sources' not in client.call_args_list[0].args[2]
    assert client.call_args_list[1].args[2]['previous_sources'][0]['published_text']==prior['published_text']


@pytest.mark.parametrize('text,prior',[
    ('Bank cuts policy rate to 3% from 4%',previous('Bank cuts policy rate to 3%')),
    ('Australia Q3 CPI rises 1%',previous('Australia CPI rises 1%')),
    ('Australia weighted median CPI rises 1%',previous('Australia trimmed mean CPI rises 1%')),
    ('Bank will not raise rates',previous('Bank will raise rates')),
    ('Bank corrected its policy statement',previous('Bank issues its policy statement')),
])
def test_reviewer_cannot_suppress_new_quantity_period_measure_negation_or_correction(text,prior):
    current={**event(),'normalized_evidence':[{'text':text}]}
    prior['published_text']=prior['evidence']
    assert duplicate_reference(review(True,duplicate_of=42),[prior],current) is None


def test_new_fact_or_unsupplied_reference_never_suppresses():
    assert duplicate_reference(review(True,duplicate_of=42,material_new_fact=True),[previous()],event()) is None
    client=Mock(side_effect=[(draft(),{}),(review(True,duplicate_of=99),{}),
                            (draft(),{}),(review(True,duplicate_of=99),{})])
    with pytest.raises(AnalysisFailure,match='valid_duplicate_reference'):
        CanonicalAnalyzer(client,previous_publications=[previous()])(event())


def test_duplicate_publication_persists_across_restart_without_losing_analysis(env):
    p,s,members=env
    item=source(event_type='market',event_refs=(),title=event()['title'],
                source_excerpt=event()['normalized_evidence'][0]['text'])
    eid=p.ingest(item,NOW)
    client=Mock(side_effect=[(draft(),{}),(review(True,duplicate_of=42),{})])
    assert p.analyze(eid,CanonicalAnalyzer(client,previous_publications=[previous()]),NOW)=='done'
    assert s.event(eid)['reason']=='duplicate_publication'
    assert p.queue(eid,NOW)==[]
    p=Pipeline(Store(s.connect,sandbox=True),p.universe,lambda:members,not_before=p.not_before)
    assert p.queue(eid,NOW+timedelta(minutes=1))==[]
    assert p.ingest(item,NOW+timedelta(minutes=1))==eid
    assert s.event(eid)['reason']=='duplicate_publication'
    with s.transaction() as c:
        assert json.loads(c.execute('SELECT result_json FROM ne_analysis WHERE event_id=?',(eid,)).fetchone()['result_json'])==draft()


def test_retrieval_uses_sent_immutable_version_and_excludes_pending_future_old(env):
    p,s,_=env
    text='The central bank said policy rates may rise if inflation persists; no decision was announced.'
    item=source(event_type='market',event_refs=(),title='Central bank policy rates statement',source_excerpt=text)
    eid=p.ingest(item,NOW)
    version=s.event(eid)['evidence_version']
    with s.transaction(True) as c:
        c.execute('CREATE TABLE scanner_telegram_outbox(id INTEGER,status TEXT,event_type TEXT,sent_at TEXT,dedupe_key TEXT,message TEXT)')
        c.execute('CREATE TABLE ne_outbox(dedupe_key TEXT,event_id TEXT,version TEXT)')
        for i,status,at in [(1,'sent',NOW),(2,'pending',NOW),(3,'sent',NOW+timedelta(minutes=1)),(4,'sent',NOW-timedelta(hours=7))]:
            c.execute('INSERT INTO scanner_telegram_outbox VALUES(?,?,?,?,?,?)',(i,status,'market_news',at.isoformat(),str(i),'הבנק מסר שהריבית עשויה לעלות אם האינפלציה תימשך.'))
            c.execute('INSERT INTO ne_outbox VALUES(?,?,?)',(str(i),eid,version))
        # The published snapshot stays original even if current metadata changes.
        c.execute("UPDATE ne_events SET status='analyzed',body_json=? WHERE event_id=?",(json.dumps({'title':'unpublished correction','published_at':NOW.isoformat()}),eid))
    current={**event(),'event_type':'market','published_at':NOW.isoformat()}
    selected=candidates(s,current,NOW)
    assert [v['id'] for v in selected]==[1]
    assert 'unpublished correction' not in selected[0]['evidence']
    assert candidates(s,{**current,'tickers':['AAPL']},NOW)==[]
    with s.transaction(True) as c:
        c.execute("UPDATE ne_events SET reason='source_retracted' WHERE event_id=?",(eid,))
    assert candidates(s,current,NOW)==[]
