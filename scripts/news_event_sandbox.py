"""Offline canonical ingest/report from exported source rows; never sends/AI.

Example: python scripts/news_event_sandbox.py --sandbox-directory TEMP_DIR
  --sources sources.json --universe stock-universe.json --not-before ISO_UTC
Optional --sec-mapping official-ticker-cache.json adds verified issuer CIKs.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'service/server'))
from news_events.model import Source
from news_events.store import Store
from news_events.engine import Pipeline
from news_events.bridge import scanner_identity_catalog
from news_events.reporting import report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sandbox-directory',required=True,type=Path)
    parser.add_argument('--sources',required=True,type=Path)
    parser.add_argument('--universe',required=True,type=Path)
    parser.add_argument('--sec-mapping',type=Path)
    parser.add_argument('--not-before',required=True)
    args=parser.parse_args()
    directory=args.sandbox_directory.resolve()
    directory.mkdir(parents=True,exist_ok=True)
    db=directory/'phase2-events.sqlite'
    def connect():
        c=sqlite3.connect(db);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
    store=Store(connect,sandbox=True);store.install()
    universe=scanner_identity_catalog(json.loads(args.universe.read_text(encoding='utf-8')),
        json.loads(args.sec_mapping.read_text(encoding='utf-8')) if args.sec_mapping else None)
    pipeline=Pipeline(store,universe,lambda:(set(),set()),not_before=args.not_before)
    now=datetime.now(timezone.utc)
    for row in json.loads(args.sources.read_text(encoding='utf-8')):pipeline.ingest(Source(**row),now)
    print(json.dumps(report(store,now),ensure_ascii=True,indent=2))


if __name__=='__main__':main()
