"""Hide only new canonical backlog projections; preserve an audit of links.

Does not delete source/news/event/trade data or touch legacy news relationships.
Reconstructed erroneous canonical display links are archived before unlinking.
"""
import json
from .runtime import connect,now
from .model import timestamp


def run():
    stamp=timestamp(now());hidden=unlinked=0
    with connect() as c:
        c.execute('SELECT pg_advisory_xact_lock(719329,2)')
        rows=c.execute('''SELECT p.event_id,p.news_id FROM ne_projection p JOIN ne_events e ON e.event_id=p.event_id
            JOIN scanner_news n ON n.id=p.news_id WHERE e.reason IN ('backlog_blocked','stale_or_future')
            AND n.provider='canonical_events' AND n.analysis_status!='stale_skipped' ''').fetchall()
        audit=[]
        for row in rows:
            links=[dict(r) for r in c.execute('SELECT * FROM scanner_trade_news WHERE news_id=?',(row['news_id'],))]
            audit.append({**dict(row),'links':links})
            c.execute("UPDATE scanner_news SET analysis_status='stale_skipped' WHERE id=?",(row['news_id'],));hidden+=1
            c.execute('DELETE FROM scanner_trade_news WHERE news_id=?',(row['news_id'],));unlinked+=len(links)
        if rows:
            c.execute('INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)',
                ('canonical_projection_repair:'+stamp,json.dumps(audit),stamp))
    return dict(hidden_backlog_projections=hidden,archived_then_unlinked=unlinked)


if __name__=='__main__':
    import config
    print(json.dumps(run()))
