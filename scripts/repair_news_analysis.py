"""Back up first; quarantine contaminated summaries and requeue failed news once.

No trades or Telegram messages are created. Run with --apply after review.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service/server'))
import database


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if database.using_postgres():
        raise SystemExit('This local repair requires a SQLite snapshot.')
    path=Path(database._SQLITE_DB_PATH).resolve()
    read=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);read.row_factory=sqlite3.Row
    columns={r[1] for r in read.execute('PRAGMA table_info(scanner_news)')}
    version='quality_version' if 'quality_version' in columns else '0'
    rows=[dict(r) for r in read.execute(f'''SELECT n.*,j.status job_status FROM scanner_news n
        LEFT JOIN scanner_news_jobs j ON j.news_id=n.id WHERE {version}=0''')]
    targets=[]
    for r in rows:
        source=(r['source_facts_json'] or r['title'] or '').lower()
        summary=(r['summary_he'] or '')
        contaminated=any(term in summary.lower() and term not in source for term in ('macd','rsi','ema20','טכני','ממוצעים נעים'))
        if r['job_status'] in ('retry','failed') or contaminated:
            targets.append((r['id'],contaminated))
    print(json.dumps({'affected_ids':[r[0] for r in targets],'apply':args.apply}))
    if not args.apply:
        read.close();return
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=ROOT/'.runtime'/f'news-quality-backup-{stamp}.db'
    backup.parent.mkdir(exist_ok=True)
    dest=sqlite3.connect(backup);read.backup(dest);dest.close();read.close()
    database.init_database()
    conn=database.get_db_connection();cur=conn.cursor();database.begin_write_transaction(cur)
    now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    for news_id,contaminated in targets:
        # A persistent upgrade marker prevents repeated runs resetting the budget.
        cur.execute('SELECT analysis_error FROM scanner_news WHERE id=?',(news_id,))
        if cur.fetchone()['analysis_error']=='quality_upgrade_pending':continue
        if contaminated:
            cur.execute("""UPDATE scanner_news SET title_he=NULL,summary_he=NULL,interpretation_he=NULL,
                sentiment=NULL,impact=NULL,materiality=NULL,relevance=NULL WHERE id=?""",(news_id,))
        cur.execute("UPDATE scanner_news SET analysis_status='pending_analysis',quality_version=-2,analysis_error='quality_upgrade_pending',updated_at=? WHERE id=?",(now,news_id))
        cur.execute("""INSERT INTO scanner_news_jobs(news_id,priority,status,attempts,next_attempt_at,created_at,updated_at)
            VALUES(?,?,'pending',0,?,?,?) ON CONFLICT(news_id) DO UPDATE SET
            priority=excluded.priority,status='pending',attempts=0,next_attempt_at=excluded.next_attempt_at,last_error=NULL,updated_at=excluded.updated_at""",
            (news_id,10 if contaminated else 90,now,now,now))
    conn.commit();conn.close()
    print('Backup:',backup)


if __name__=='__main__':main()
