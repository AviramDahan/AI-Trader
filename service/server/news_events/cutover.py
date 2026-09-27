"""Operator command, only while scanner and Telegram dispatcher are STOPPED.

No DB restore, no trading changes. Migration leaves Phase 1 active. Transition
fences queued legacy news and snapshots checkpoint hashes for the release audit.
"""
import argparse
import hashlib
import json
from .control import NEWS_TYPES
from .model import canonical_url, timestamp
from .runtime import connect, now


def switch(mode,reason):
    if mode not in ('phase1','canonical'):raise ValueError('invalid_mode')
    current=timestamp(now())
    with connect() as c:
        # Same session locks used by cloud_runtime.RoleLease. Fail rather than
        # switching underneath either producer or a request already in flight.
        for key in (11,13):
            if not c.execute('SELECT pg_try_advisory_xact_lock(719322,?) AS locked',(key,)).fetchone()['locked']:
                raise RuntimeError('stop_scanner_and_telegram_before_cutover')
        prior=c.execute('SELECT * FROM ne_control WHERE id=1 FOR UPDATE').fetchone()
        if prior['mode']==mode:return dict(mode=mode,changed=False,not_before=prior['not_before'])
        if c.execute("SELECT 1 FROM scanner_telegram_outbox WHERE status='sending' AND event_type IN ('market_news','position_news','watchlist_news','stock_news') LIMIT 1").fetchone():
            raise RuntimeError('ambiguous_telegram_delivery_requires_reconciliation')
        # New-source discovery must not republish a previous-path event.
        for row in c.execute('''SELECT DISTINCT n.url,a.channel FROM scanner_news_broadcast_alerts a
            JOIN scanner_news n ON n.id=a.news_id UNION SELECT DISTINCT n.url,'personal'
            FROM scanner_news_alerts a JOIN scanner_news n ON n.id=a.news_id
            UNION SELECT DISTINCT n.url,'personal' FROM scanner_news_watchlist_alerts a JOIN scanner_news n ON n.id=a.news_id''').fetchall():
            try:url=canonical_url(row['url'])
            except ValueError:continue
            topic={'market':'market_news','stock':'important_stock_news','personal':'portfolio_watchlist'}[row['channel']]
            c.execute('INSERT INTO ne_cutover_receipts VALUES(?,?,?) ON CONFLICT DO NOTHING',(url,topic,current))
        c.execute("""UPDATE scanner_telegram_outbox SET status='cancelled',last_error='news_cutover_fence'
            WHERE status IN ('pending','retry') AND event_type IN ('market_news','position_news','watchlist_news','stock_news')""")
        c.execute('UPDATE ne_control SET mode=?,not_before=?,epoch=epoch+1,changed_at=?,reason=? WHERE id=1',(mode,current,current,reason))
        checkpoints=[dict(r) for r in c.execute('SELECT provider,checkpoint_json FROM scanner_news_providers ORDER BY provider')]
        digest=hashlib.sha256(json.dumps(checkpoints,sort_keys=True).encode()).hexdigest()
        c.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('news_canonical_cutover',?,?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
            (json.dumps(dict(mode=mode,not_before=current,checkpoint_digest=digest)),current))
    return dict(mode=mode,changed=True,not_before=current,checkpoint_digest=digest)


def main():
    import config
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['canonical','phase1']);p.add_argument('--reason',default='operator_approved')
    args=p.parse_args();print(json.dumps(switch(args.mode,args.reason)))


if __name__=='__main__':main()
