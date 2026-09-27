"""Event-store transaction/claim/recovery validation on real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import threading


def test_canonical_concurrency_restart_and_isolation(pg):
    from database import get_db_connection
    from news_events.store import Store
    from news_events.engine import Pipeline,Analysis
    from news_events.model import Source
    now=datetime(2026,9,27,12,tzinfo=timezone.utc)
    store=Store(get_db_connection,sandbox=True);store.install()
    p=Pipeline(store,{'AAPL':{'company':'Apple Inc.'}},lambda:({'AAPL'},set()),not_before=now-timedelta(days=1))
    def source(provider):
        return Source(provider,'first','https://example.org/articles/12345',provider,now.isoformat(),now.isoformat(),
            'Apple Inc. financial results','Apple Inc. announced quarterly financial results with higher revenue while maintaining its current corporate guidance.',
            event_type='earnings',rights='approved')
    with ThreadPoolExecutor(3) as pool:ids=list(pool.map(lambda provider:p.ingest(source(provider),now),['yahoo','benzinga','telegram']))
    assert len(set(ids))==1
    entered=threading.Event();release=threading.Event()
    result=dict(related=True,title_he='אפל פרסמה תוצאות',summary_he='החברה פרסמה תוצאות ושמרה על התחזית.',
        interpretation_he='ייתכן שיש השפעה על החברה.',sentiment='positive',materiality='high',relevance=.95)
    def ai(event):entered.set();assert release.wait(5);return Analysis(result)
    with ThreadPoolExecutor(2) as pool:
        task=pool.submit(p.analyze,ids[0],ai,now);assert entered.wait(5)
        assert p.analyze(ids[0],lambda event:None,now)=='running'
        with store.transaction(True) as c:store.metric(c,'pg_probe','no_ai_transaction',now.isoformat())
        release.set();assert task.result()=='done'
    assert len(p.deliver_preview(ids[0],now))==1
    restarted=Pipeline(Store(get_db_connection,sandbox=True),p.universe,p.membership,not_before=p.not_before)
    restarted.store.install();assert restarted.deliver_preview(ids[0],now)==[]
    with store.transaction() as c:
        assert c.execute('SELECT COUNT(*) AS n FROM ne_events').fetchone()['n']==1
        assert c.execute('SELECT COUNT(*) AS n FROM ne_sources').fetchone()['n']==3
        assert c.execute('SELECT COUNT(*) AS n FROM ne_analysis').fetchone()['n']==1
        assert c.execute('SELECT COUNT(*) AS n FROM ne_delivery').fetchone()['n']==1
        assert c.execute('SELECT COUNT(*) AS n FROM scanner_trades').fetchone()['n']==0
