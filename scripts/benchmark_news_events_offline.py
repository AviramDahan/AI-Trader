"""Synthetic local core timing only. No network, model, production DB or .env."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import sqlite3
import statistics
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'service/server'))
from news_events.model import Source
from news_events.store import Store
from news_events.engine import Pipeline
from news_events.reporting import report

with tempfile.TemporaryDirectory(prefix='news-phase2-timing-') as directory:
    db=Path(directory)/'sandbox.sqlite'
    def connect():
        c=sqlite3.connect(db);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
    store=Store(connect,sandbox=True);store.install()
    now=datetime.now(timezone.utc)
    pipeline=Pipeline(store,{'TEST':{'company':'Fixture Company Inc.'}},lambda:(set(),set()),not_before=now-timedelta(days=1))
    elapsed=[]
    for n in range(30):
        start=time.perf_counter()
        for provider in ('fixture_a','fixture_b','fixture_c','fixture_d'):
            item=Source(provider,str(n),f'https://example.invalid/articles/{10000+n}',provider,
                now.isoformat(),now.isoformat(),f'Fixture Company Inc. financial results release {n}',
                f'Fixture Company Inc. announced results for isolated test case {n} while preserving its prior corporate guidance and assumptions.',
                event_type='earnings',rights='internal_review')
            pipeline.ingest(item,now)
        elapsed.append((time.perf_counter()-start)*1000)
    metrics=report(store,now)
    print(json.dumps({'measurement':'synthetic SQLite ingest of 4 providers per event; no AI',
        'events':metrics['canonical_events'],'source_versions':metrics['source_versions'],
        'duplicate_evidence_versions':metrics['cross_source_duplicate_versions'],
        'median_ms_per_event':round(statistics.median(elapsed),3),
        'p95_ms_per_event':round(sorted(elapsed)[int(len(elapsed)*.95)-1],3),
        'actual_ai_calls':0,'actual_cost':0,'public_messages':0}))
