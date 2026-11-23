"""Private, bounded read-side projections for news operations."""
import json
import re
from collections import Counter, defaultdict
from datetime import timedelta

from news_events.control import state

NEWS_LIMIT = 10000
WATCH_LIMIT = 64
FILING_LIMIT = 512
NEWS_TYPES = (
    'market_news', 'stock_news', 'watchlist_news', 'position_news',
    'watchlist_news_correction', 'correction', 'trump_truth_post',
    'sec_intelligence', 'ownership_activity', 'buyback_activity', 'analyst_update', 'company_report',
)
CANONICAL_ROUTES = frozenset({'market_news', 'portfolio_watchlist', 'important_stock_news'})
REASONS = frozenset({
    'identity_unverified', 'insufficient_information', 'quality_failed',
    'duplicate', 'stale_content', 'news_pipeline_fenced',
    'company_report_requires_structured_filing', 'disabled_by_configuration',
    'missing_credentials', 'news_cutover_fence', 'canonical_safety_rollback',
})
LEGACY_STAGES = {
    'pending_analysis': 'pending', 'analyzed': 'analyzed', 'analysis_error': 'error',
    'duplicate_event': 'duplicate', 'stale_skipped': 'stale', 'rejected': 'filtered',
    'insufficient_information': 'filtered', 'disabled': 'disabled',
    'pending_translation': 'pending', 'translated': 'translated', 'public_translated': 'translated',
}
CANONICAL_STAGES = {
    'pending': 'pending', 'analyzed': 'analyzed', 'blocked': 'filtered',
    'error': 'error', 'duplicate': 'duplicate', 'processing': 'pending',
}


def _stamp(at):
    # Retained writers use both UTC Z and +00:00. Compare by whole seconds.
    return at.strftime('%Y-%m-%dT%H:%M:%S')


def _params(values):
    return ','.join('?' for _ in values)


def _safe_provider(provider):
    return provider if isinstance(provider, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,48}', provider) else 'other'


def _sources(conn, mode, start, end, acknowledged):
    if mode == 'canonical':
        rows = conn.execute("""SELECT s.provider_id provider, s.event_id item,
            e.status stage, e.reason, s.active
            FROM ne_sources s JOIN ne_events e ON e.event_id=s.event_id
            WHERE s.collected_at>=? AND s.collected_at<? LIMIT ?""",
                            (start, end, NEWS_LIMIT + 1)).fetchall()
        stages = CANONICAL_STAGES
    else:
        rows = conn.execute("""SELECT s.provider, s.news_id item, n.analysis_status stage,
            n.analysis_error reason, 1 active
            FROM scanner_news_sources s JOIN scanner_news n ON n.id=s.news_id
            WHERE s.collected_at>=? AND s.collected_at<? LIMIT ?""",
                            (start, end, NEWS_LIMIT + 1)).fetchall()
        stages = LEGACY_STAGES
    receipts = Counter()
    items = defaultdict(dict)
    for row in rows[:NEWS_LIMIT]:
        provider = _safe_provider(row['provider'])
        receipts[provider] += 1
        if row['active']:
            items[provider][row['item']] = row
    checks = {}
    if mode == 'phase1':
        last_checks = conn.execute("""SELECT provider,last_attempt_at,last_received_count,
            last_ingested_count,last_duplicate_count,last_rejected_assignment_count,last_rejected_date_count
            FROM scanner_news_providers WHERE last_attempt_at>=? AND last_attempt_at<?
              AND status IN ('ok','no_new','not_modified','degraded')
            ORDER BY last_attempt_at DESC,provider LIMIT 49""", (start, end)).fetchall()
        for row in last_checks[:48]:
            provider = _safe_provider(row['provider'])
            if provider == 'other':
                continue
            checks[provider] = dict(at=row['last_attempt_at'], counts={
                'received': row['last_received_count'], 'ingested': row['last_ingested_count'],
                'duplicate': row['last_duplicate_count'],
                'rejected_assignment': row['last_rejected_assignment_count'],
                'rejected_date': row['last_rejected_date_count'],
            })
            receipts.setdefault(provider, 0)
    result = []
    for provider, count in sorted(receipts.items(), key=lambda pair: (-pair[1], pair[0])):
        counts = Counter()
        reasons = Counter()
        for row in items[provider].values():
            counts[stages.get(row['stage'], 'other')] += 1
            if row['reason']:
                reasons[row['reason'] if row['reason'] in REASONS else 'other'] += 1
        result.append(dict(provider=provider, receipts=count, items=len(items[provider]),
                           linked_acknowledged=sum(item in acknowledged for item in items[provider]),
                           stages=dict(counts), reasons=dict(reasons), latest_check=checks.get(provider)))
    return dict(rows=result[:48], partial=len(rows) > NEWS_LIMIT or len(result) > 48 or
                (mode == 'phase1' and len(last_checks) > 48))


def _delivery(conn, mode, start, end):
    # Local and legacy deployments may not have the canonical link table.
    linked = 'links.topic, links.event_id' if mode == 'canonical' else 'NULL AS topic, NULL AS event_id'
    join = 'LEFT JOIN ne_outbox links ON links.dedupe_key=o.dedupe_key' if mode == 'canonical' else ''
    rows = conn.execute(f"""SELECT o.event_type, o.status, o.sent_at, o.created_at, o.last_error,
            o.dedupe_key, {linked}
        FROM scanner_telegram_outbox o {join}
        WHERE o.event_type IN ({_params(NEWS_TYPES)}) AND
            ((o.created_at>=? AND o.created_at<?) OR
             (o.status='sent' AND o.sent_at>=? AND o.sent_at<?))
        LIMIT ?""", (*NEWS_TYPES, start, end, start, end, NEWS_LIMIT + 1)).fetchall()
    groups = defaultdict(Counter)
    reasons = defaultdict(Counter)
    acknowledged = set()
    for row in rows[:NEWS_LIMIT]:
        topic = row['topic']
        key = ('canonical_route', topic) if topic in CANONICAL_ROUTES else ('message_type', row['event_type'])
        counts = groups[key]
        if start <= row['created_at'] < end:
            counts['queued_in_window'] += 1
            status = row['status']
            if status in {'failed', 'cancelled', 'disabled'}:
                counts[status] += 1
                reason = row['last_error']
                if reason:
                    reasons[key][reason if reason in REASONS else 'other'] += 1
            elif status != 'sent':
                counts['awaiting_ack'] += 1
        if row['status'] == 'sent' and start <= (row['sent_at'] or '') < end:
            counts['acknowledged'] += 1
            if mode == 'canonical':
                if row['event_id']:
                    acknowledged.add(row['event_id'])
            else:
                match = re.match(r'^(market-news|stock-news|watchlist-news|news):([0-9]{1,18}):', row['dedupe_key'])
                if match:
                    acknowledged.add(int(match.group(2)))
    return (dict(rows=[dict(basis=basis, route=route, counts=dict(counts), reasons=dict(reasons[basis, route]))
                       for (basis, route), counts in sorted(groups.items())],
                 partial=len(rows) > NEWS_LIMIT), acknowledged)


def _earnings(conn, start, end):
    watch = conn.execute("""SELECT ticker FROM scanner_news_watchlist WHERE enabled=1
        ORDER BY ticker LIMIT ?""", (WATCH_LIMIT + 1,)).fetchall()
    universe = conn.execute("""SELECT observed_at, members_json FROM si_universe_snapshots
        WHERE observed_at<? ORDER BY observed_at DESC,id DESC LIMIT 1""", (end,)).fetchone()
    members = json.loads(universe['members_json']) if universe else {}
    tickers = {}
    for row in watch[:WATCH_LIMIT]:
        ticker = row['ticker']
        member = members.get(ticker, {})
        tickers[ticker] = member.get('issuer_cik') if member.get('mapping') == 'verified' else None
    issuers = sorted(set(tickers.values()) - {None})
    by_issuer = defaultdict(Counter)
    checkpoints = {}
    filings = []
    if issuers:
        checkpoints = {row['issuer_cik']: row['last_checked_at'] for row in conn.execute(
            f"""SELECT issuer_cik,last_checked_at FROM si_checkpoints
            WHERE issuer_cik IN ({_params(issuers)}) AND last_checked_at<?""", (*issuers, end)).fetchall()}
        filings = conn.execute(f"""SELECT j.issuer_cik,j.status,o.status delivery,o.sent_at
            FROM si_filing_jobs j LEFT JOIN scanner_telegram_outbox o
            ON o.dedupe_key='sec-intelligence:' || j.accession AND o.event_type='sec_intelligence'
            WHERE j.issuer_cik IN ({_params(issuers)}) AND j.accepted_at>=? AND j.accepted_at<?
                AND j.form IN ('10-Q','10-K','10-Q/A','10-K/A')
            LIMIT ?""", (*issuers, start, end, FILING_LIMIT + 1)).fetchall()
        for row in filings[:FILING_LIMIT]:
            counts = by_issuer[row['issuer_cik']]
            counts['discovered'] += 1
            if row['status'] == 'processed':
                counts['processed'] += 1
            if row['delivery'] == 'sent' and row['sent_at'] and row['sent_at'] < end:
                counts['acknowledged'] += 1
            elif row['delivery'] in {'failed', 'cancelled', 'disabled'}:
                counts['delivery_stopped'] += 1
            elif row['delivery']:
                counts['awaiting_ack'] += 1
            elif row['status'] == 'processed':
                counts['processed_without_notice'] += 1
    return dict(rows=[dict(ticker=ticker, discovery_checked_at=checkpoints.get(issuer),
                           counts=dict(by_issuer[issuer]) if issuer else None)
                      for ticker, issuer in tickers.items()],
                partial=len(watch) > WATCH_LIMIT or len(filings) > FILING_LIMIT,
                mapping_at=universe['observed_at'] if universe else None)


def build(conn, now):
    mode = state(conn)['mode']
    end = _stamp(now)
    start = _stamp(now - timedelta(hours=6))
    report_start = _stamp(now - timedelta(days=30))
    delivery, acknowledged = _delivery(conn, mode, start, end)
    sources = _sources(conn, mode, start, end, acknowledged)
    sources['partial'] |= delivery['partial']
    return dict(observed_at=now.isoformat(), status='observed', mode=mode,
                news_hours=6, report_days=30, sources=sources,
                delivery=delivery, earnings=_earnings(conn, report_start, end))
