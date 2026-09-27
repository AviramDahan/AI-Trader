"""Read-only release integrity/readiness. Output contains no secrets or news text."""
import hashlib
import json
import os
from .runtime import connect
from .control import state


def inspect():
    result={}
    with connect() as c:
        c.execute('SET TRANSACTION READ ONLY')
        for table in ('scanner_trades','scanner_fills','scanner_accounts','scanner_orders'):
            rows=[dict(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY id')]
            result[table]={'count':len(rows),'hash':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()}
        result['positions']=[dict(r) for r in c.execute("SELECT is_shadow,count(*) n FROM scanner_trades WHERE status='open' GROUP BY is_shadow")]
        result['schema']=c.execute('SELECT MAX(version) v FROM schema_migrations').fetchone()['v']
        result['services']=[dict(r) for r in c.execute("SELECT component,status,last_success_at FROM scanner_service_status WHERE component IN ('monitor','telegram','backup','news_ai','news_feed','news_stream')")]
        result['control']=state(c)
        result['broken_projection']=c.execute('''SELECT count(*) n FROM ne_projection p LEFT JOIN scanner_news n ON n.id=p.news_id
            WHERE n.id IS NULL''').fetchone()['n']
        result['canonical_outbox']=[dict(r) for r in c.execute("SELECT status,count(*) n FROM scanner_telegram_outbox WHERE dedupe_key LIKE 'canonical:%' GROUP BY status")]
        result['legacy_pending']=c.execute("SELECT count(*) n FROM scanner_telegram_outbox WHERE status IN ('pending','retry','sending') AND event_type IN ('market_news','position_news','watchlist_news','stock_news') AND dedupe_key NOT LIKE 'canonical:%'").fetchone()['n']
    result['models']={k:os.getenv(k) for k in ('OPENROUTER_MODEL','OPENROUTER_NEWS_MODEL','STOCK_SCANNER_FINAL_AI_MODEL','STOCK_SCANNER_AI_CANDIDATE_LIMIT')}
    return result


if __name__=='__main__':
    import config
    print(json.dumps(inspect(),default=str))
