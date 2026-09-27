"""Read-only real-sample replay; never invokes AI, queues news or writes a DB.

Run in an environment with DB read access. Prints only news/source facts and
measurements. No credentials or provider response/error bodies. This is an
evidence/eligibility comparison, NOT a measured model-quality benchmark.
"""
import hashlib
import json
import os
import time
import config
from database import get_db_connection
from news_evidence import extract, fetch_filing, missing_information, EvidenceError

SAMPLE_IDS = (84, 96, 99, 384, 400, 409, 420, 426, 434, 436, 438, 519, 618, 360, 751)
with get_db_connection() as c:
    c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
    rows = [dict(r) for r in c.execute('''SELECT id,title,url,provider,published_at,scope,
        verified_tickers_json,source_facts_json,analysis_status,materiality FROM scanner_news
        WHERE id IN (''' + ','.join('?' for _ in SAMPLE_IDS) + ') ORDER BY id', SAMPLE_IDS)]
    personal = {r['ticker'] for r in c.execute("SELECT ticker FROM scanner_trades WHERE status='open' AND is_shadow=0 AND remaining_quantity>0 UNION SELECT ticker FROM scanner_news_watchlist WHERE enabled=1")}

for row in rows:
    report = dict(id=row['id'], provider=row['provider'], title=row['title'],
                  original_published_at=row['published_at'], old_status=row['analysis_status'],
                  old_materiality=row['materiality'], missing_information=missing_information(row),
                  model_calls=0, model_cost=0, public_messages=0)
    tickers = sorted(personal.intersection(json.loads(row['verified_tickers_json'] or '[]')))
    if row['provider'] != 'sec_edgar' or not tickers:
        report.update(after='unchanged_no_authorized_exact_event_adapter', seconds=0)
    else:
        start = time.monotonic()
        try:
            raw, url = fetch_filing(row['url'], os.getenv('NEWS_SEC_USER_AGENT', ''))
            value = extract(raw, url, tickers)
            report.update(after='verified_source_excerpt_available', source_url=url,
                          raw_sha256=hashlib.sha256(raw.encode()).hexdigest(), raw_bytes=len(raw.encode()),
                          excerpt=value['selected_excerpt'], content_version=value['content_version'],
                          excerpt_chars=len(value['selected_excerpt']), verified_ticker=value['ticker'])
        except EvidenceError as exc:
            report.update(after='insufficient_information', reason=exc.reason, http_status=exc.status)
        report['seconds'] = round(time.monotonic() - start, 3)
    print(json.dumps(report, ensure_ascii=True), flush=True)
