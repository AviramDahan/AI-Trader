"""Bounded, deterministic earnings-release producer for independent PEAD.

Existing canonical providers discover original releases for the configured
universe. A feed headline is only a discovery hint, never timing evidence.
Original-page structured datetime + issuer-body exchange/ticker + official CIK
mapping are required. No LLM, UI fetch, SEC acceptance-time substitution, new
public feed, paper order, or Telegram side effect. Unknown is retained.

Facts are immutable candidate-journal observations; checkpoints and recoverable
bounded jobs reuse scanner_settings. No schema change or historical rewrite.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
VERSION = 'verified_earnings_release_v1'
MAX_BODY = 2 * 1024 * 1024
MAX_JOBS = 2000
CURSOR = 'pead_release_cursor_v1'
COVERAGE = 'pead_release_coverage_v1'
PREFIX = 'pead_release_job_v1:'
HOSTS = {'prnewswire': {'www.prnewswire.com', 'prnewswire.com'},
         'globenewswire': {'www.globenewswire.com', 'globenewswire.com'}}


def instant(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('release_timezone_required')
    return parsed.astimezone(UTC)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def endpoint(url, provider):
    """A closed publisher/path allowlist, not a user-provided crawling service."""
    p = urlsplit(str(url))
    if (p.scheme != 'https' or p.hostname not in HOSTS.get(provider, ()) or p.username or p.password or
            p.port not in (None, 443) or p.fragment or '\\' in p.path or '%' in p.path or
            not re.fullmatch(r'/[A-Za-z0-9_./-]{1,1500}', p.path)):
        raise ValueError('release_unsafe_source')
    path = '/news-releases/' if provider == 'prnewswire' else '/news-release/'
    if not p.path.startswith(path) or not p.path.endswith('.html'):
        raise ValueError('release_unsupported_path')
    return urlunsplit(('https', p.netloc.lower(), p.path, '', ''))


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.parts, self.ld, self.links = {}, [], [], []
        self.hidden = 0
        self.script = False
        self.script_parts = []
        self.nodes = self.text_size = 0
        self.paragraphs, self.paragraph = [], None

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > 50000:
            raise ValueError('release_html_node_limit')
        attrs = dict(attrs)
        if tag == 'p' and not self.hidden:
            self.paragraph = []
        if tag == 'meta':
            key = (attrs.get('property') or attrs.get('name') or '').lower()
            if key in {'article:published_time', 'date', 'datepublished'}:
                self.meta.setdefault(key, []).append(attrs.get('content', '')[:200])
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.links.append(attrs.get('href', '')[:1600])
        if tag in {'script', 'style', 'noscript'}:
            self.hidden += 1
            if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
                self.script = True
                self.script_parts = []
        if tag in {'p', 'div', 'br', 'h1', 'h2', 'section', 'article'} and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'p' and self.paragraph is not None:
            self.paragraphs.append(' '.join(''.join(self.paragraph).split()))
            self.paragraph = None
        if tag in {'script', 'style', 'noscript'}:
            if tag == 'script' and self.script:
                self.ld.append(''.join(self.script_parts))
                self.script = False
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if self.script:
            self.script_parts.append(data)
            if sum(map(len, self.script_parts)) > 32768:
                raise ValueError('release_structured_metadata_limit')
        elif not self.hidden:
            self.text_size += len(data)
            if self.text_size > 524288:
                raise ValueError('release_text_limit')
            self.parts.append(data)
            if self.paragraph is not None:
                self.paragraph.append(data)


def _structured_dates(page):
    values = [v for entries in page.meta.values() for v in entries]
    count = 0
    stack = []
    for raw in page.ld[:16]:
        try:
            stack.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    while stack:
        node = stack.pop()
        count += 1
        if count > 256:
            raise ValueError('release_metadata_node_limit')
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            kind = node.get('@type')
            if kind in ('NewsArticle', 'Article', 'ReportageNewsArticle') or (
                    isinstance(kind, list) and 'NewsArticle' in kind):
                if isinstance(node.get('datePublished'), str):
                    values.append(node['datePublished'])
            # Only traverse embedded objects. Never dereference @context/@id.
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    dates = set()
    for value in values:
        try:
            if not re.search(r'T\d{2}:\d{2}.*(?:Z|[+-]\d{2}:?\d{2})$', value):
                continue  # Date-only/naive local metadata cannot establish release timing.
            dates.add(instant(value))
        except (TypeError, ValueError, OverflowError):
            continue
    if len(dates) != 1:
        raise ValueError('release_publication_missing_or_conflicting')
    return dates.pop()


def _actual_reporting_clauses(body):
    """Conservative assertion checks, not a general NLP/LLM classifier.

    Check both sides of the matched verb/noun phrase: negation may precede the
    verb, and a preview may put its future-publication clause AFTER 'results'.
    Unsupported language is UNKNOWN rather than promoted using a headline.
    """
    output = []
    for report in re.finditer(r'\b(?:today\s+)?(?:reported|announced|reports|announces)\b.{0,160}?'
            r'\b(?:financial|quarterly|annual)\s+results\b', body, re.I):
        before = body[max(0, report.start()-60):report.start()]
        after = body[report.end():report.end()+240].split('.')[0]
        if (re.search(r'\b(?:will|would|not|never|plans?|schedule[ds]?|conference|webcast|call|discuss|upcoming|next|expects?)\b', report.group(), re.I) or
                re.search(r"\b(?:not|never|yet\s+to|hasn't|haven't|didn't|doesn't|no\s+longer)\b", before, re.I) or
                re.search(r'\b(?:will|would|to)\s+(?:be\s+)?(?:release[ds]?|report(?:ed|s)?|announce[ds]?|publish(?:ed|es)?)\b|\bnext\s+(?:week|month)\b', after, re.I)):
            continue
        output.append(report)
    return output


def parse_release(raw, *, url, provider, catalog, first_seen_at, observed_at, processed_at,
                  previous=None):
    """Pure parser; source clocks are supplied by the actual producer, not HTML."""
    canonical = endpoint(url, provider)
    first, observed, processed = map(instant, (first_seen_at, observed_at, processed_at))
    if first > observed or observed > processed:
        raise ValueError('release_clock_order')
    if not isinstance(raw, bytes) or len(raw) > MAX_BODY:
        raise ValueError('release_body_limit')
    event_id = previous.get('event_id') if previous else 'release:' + digest(canonical)
    fact = dict(parser_version=VERSION, event_id=event_id, source_id='page:' + digest(canonical),
        event_type='EARNINGS_RELEASE', source_url=canonical, provider=provider,
        document_hash=hashlib.sha256(raw).hexdigest(), first_seen_at=first.isoformat(),
        source_observed_at=observed.isoformat(), processed_at=processed.isoformat(),
        effective_available_at=processed.isoformat(), revision=digest([canonical, hashlib.sha256(raw).hexdigest()]),
        verified=False, timing_verified=False, retracted=False, symbol=None, issuer_cik=None,
        released_at=previous.get('released_at') if previous else None, timing='UNKNOWN',
        reasons=[], coverage='approved_original_wire_pages_not_all_issuers')
    if previous:
        fact.update(symbol=previous.get('symbol'), issuer_cik=previous.get('issuer_cik'))
    try:
        page = Page()
        page.feed(raw.decode('utf-8', errors='strict'))
        page.close()
        body = ' '.join(page.paragraphs)
        if previous and re.search(r'\b(?:this|the\s+previous)\s+(?:press\s+)?release\s+'
                r'(?:has\s+been|is|was)\s+(?:retracted|withdrawn)\b', body, re.I):
            fact['retracted'] = True
            raise ValueError('release_source_retracted')
        if previous and previous.get('retracted') and not re.search(
                r'\bthis\s+(?:press\s+)?release\s+(?:has\s+been|is)\s+reinstated\b', body, re.I):
            fact['retracted'] = True
            raise ValueError('release_retraction_requires_explicit_reinstatement')
        if len(page.ld) > 16:
            raise ValueError('release_structured_metadata_limit')
        if page.links and any(endpoint(urljoin(canonical, link), provider) != canonical for link in page.links):
            raise ValueError('release_canonical_mismatch')
        release = _structured_dates(page)
        if release > observed:
            raise ValueError('release_publication_in_future')
        if previous and previous.get('released_at') and release != instant(previous['released_at']):
            raise ValueError('release_original_publication_changed')
        fact.update(released_at=release.isoformat(), published_at=release.isoformat())
        # Reporting clause must be in original body, with issuer identity in the
        # immediately preceding 400 characters, not an unrelated ticker/footer.
        reports = _actual_reporting_clauses(body)
        if not reports or not re.search(r'\b(?:quarter|fiscal\s+year|year)\b.{0,100}?\bended\b', body, re.I):
            raise ValueError('release_actual_results_not_verified')
        identities = set()
        for report in reports:
            prefix = body[max(0, report.start()-400):report.start()]
            identities.update(m.group(1).upper().replace('.', '-') for m in re.finditer(
                r'\(\s*(?:NASDAQ|NYSE|NYSE\s+AMERICAN)\s*:\s*([A-Z][A-Z0-9.-]{0,9})\s*\)', prefix, re.I))
        if len(identities) != 1:
            raise ValueError('release_issuer_identity_ambiguous')
        symbol = identities.pop()
        member = catalog.get(symbol, {})
        cik = str(member.get('cik') or '').lstrip('0')
        if not re.fullmatch(r'[1-9][0-9]{0,9}', cik):
            raise ValueError('release_official_issuer_mapping_missing')
        if previous and (symbol != previous.get('symbol') or cik != previous.get('issuer_cik')):
            raise ValueError('release_revision_identity_changed')
        fact.update(symbol=symbol, issuer_cik=cik, issuer_mapping_hash=digest(member))
        # A different-URL correction needs an explicit retained relationship;
        # this parser currently supports same-original-URL revisions only.
        if re.search(r'\b(?:correction|correcting|retraction|retracted)\b', body, re.I) and not previous:
            raise ValueError('release_correction_relationship_unknown')
        local = release.astimezone(NY)
        timing = 'BMO' if (local.hour, local.minute) < (9, 30) else 'AMC' if local.hour >= 16 else 'INTRADAY'
        fact.update(verified=True, timing_verified=True, timing=timing,
                    timing_source='original_page_structured_datePublished',
                    identity_basis='body_exchange_ticker_and_official_sec_issuer_map',
                    backfill=(observed-release).total_seconds() > 86400)
        if timing == 'INTRADAY':
            fact['reasons'].append('pead_intraday_release_not_supported')
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        allowed = str(exc) if str(exc).startswith('release_') else 'release_parser_unknown'
        fact['reasons'] = [allowed]
    return fact


def _state(c, key, default=None):
    row = c.execute('SELECT value_json FROM scanner_settings WHERE key=?', (key,)).fetchone()
    return json.loads(row['value_json']) if row else (default or {})


def _put(c, key, value, at):
    c.execute('''INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at''',
        (key, json.dumps(value, sort_keys=True, allow_nan=False), instant(at).isoformat()))


def _lock(c):
    if getattr(c, '_backend', 'sqlite') == 'postgres':
        c.execute('SELECT pg_advisory_xact_lock(719329,86)')
    else:
        c.execute('BEGIN IMMEDIATE')


def _fenced(c, owner, at, *, job_key=None, source_key=None):
    """A suspended/crashed worker may never overwrite its successor's facts."""
    lease = _state(c, 'pead_release_producer_lease_v1')
    if lease.get('owner') != owner or instant(lease['until']) <= instant(at):
        return False
    if job_key is not None:
        job = _state(c, job_key)
        return (job.get('owner') == owner and job.get('status') == 'running' and
                job.get('source_key') == source_key and
                instant(job['lease_until']) > instant(at))
    return True


def _record(c, fact):
    key = 'earnings:' + digest([fact['event_id'], fact['revision'], fact['effective_available_at']])
    if c.execute("SELECT 1 FROM scanner_candidates WHERE scan_id=? AND stage='earnings_release' LIMIT 1", (key,)).fetchone():
        return False
    c.execute('''INSERT INTO scanner_candidates(scan_id,ticker,company,stage,status,reason,metrics_json,created_at)
        VALUES(?,?,NULL,'earnings_release','observed',?,?,?)''',
        (key, fact.get('symbol') or 'UNKNOWN', ','.join(fact['reasons']) or None,
         json.dumps(fact, sort_keys=True, allow_nan=False), fact['processed_at']))
    return True


def _pending_revision(c, previous, job, at, reason):
    if previous and previous.get('released_at'):
        fact = dict(previous, verified=False, retracted=previous.get('retracted') is True or reason == 'release_source_withdrawn',
            reasons=[reason], revision=digest([job['source_key'], reason]),
            source_observed_at=instant(at).isoformat(), processed_at=instant(at).isoformat(),
            effective_available_at=instant(at).isoformat())
        _record(c, fact)


def produce(*, connect=None, catalog=None, transport=None, clock=None, enabled=None, approvals=None):
    """Existing feed worker only. At most 200 discoveries + 2 HTTP requests/cycle.

    Every network operation is outside transactions; 90-second job claims recover
    after interruption. One global producer lease prevents duplicate downloads.
    No long scanner/monitor transaction, and no access when OFF/bridge. The
    optional collection-only flag never enables PEAD discovery or admission.
    """
    from entry_discovery_capabilities import creation_allowed
    import os
    if enabled is None:
        enabled = (os.getenv('STOCK_SCANNER_PEAD_ENABLED', 'false').lower() == 'true' or
            os.getenv('STOCK_SCANNER_PEAD_RELEASE_COLLECTION_ENABLED', 'false').lower() == 'true')
    if not enabled or not creation_allowed():
        return dict(status='off', processed=0)
    from database import get_db_connection
    from news_events.providers import Transport, ProviderFailure
    connect = connect or get_db_connection
    clock = clock or (lambda: datetime.now(UTC))
    at = instant(clock())
    if approvals is None:
        from news_events.provider_config import configured
        approvals = {c.provider_id for c in configured() if c.enabled and c.rights == 'approved'}
    approvals = set(approvals) & set(HOSTS)
    if catalog is None:
        from news_pipeline import ROOT, SEC_MAP_CACHE
        from news_events.bridge import scanner_identity_catalog
        try:
            universe = json.loads((ROOT / '.runtime/stock-universe.json').read_text(encoding='utf-8'))
            mapping = json.loads(SEC_MAP_CACHE.read_text(encoding='utf-8'))
            if any(not 0 <= at.timestamp()-float(snapshot['fetched_at']) <= 7*86400
                   for snapshot in (universe, mapping)):
                raise ValueError('stale_identity_mapping')
            catalog = scanner_identity_catalog(universe, mapping)
        except (OSError, ValueError, KeyError):
            return dict(status='unknown', reason='official_universe_issuer_mapping_unavailable', processed=0)
    owner = uuid.uuid4().hex
    with connect() as c:
        _lock(c)
        lease = _state(c, 'pead_release_producer_lease_v1')
        if lease and instant(lease['until']) > at:
            return dict(status='busy', processed=0)
        _put(c, 'pead_release_producer_lease_v1', dict(owner=owner, until=(at+timedelta(seconds=90)).isoformat()), at)
    summary = dict(status='ready', processed=0, verified=0, unknown=0, discovered=0,
        coverage='approved_original_wire_pages_not_all_issuers', reasons={}, observed_at=at.isoformat())
    try:
        with connect() as c:
            _lock(c)
            if not _fenced(c, owner, clock()):
                return dict(summary, status='degraded', reasons={'release_worker_lease_lost': 1})
            checkpoint = _state(c, CURSOR)
            since = checkpoint.get('collected_at', (at-timedelta(days=90)).isoformat())
            key = checkpoint.get('source_key', '')
            rows = c.execute('''SELECT source_key,provider_id,body_json,collected_at,source_id,active
                FROM ne_sources WHERE collected_at>? OR (collected_at=? AND source_key>?)
                ORDER BY collected_at,source_key LIMIT 200''', (since, since, key)).fetchall()
            pending = c.execute('''SELECT COUNT(*) n FROM scanner_settings WHERE key LIKE ? AND
                (value_json LIKE '%"status": "queued"%' OR value_json LIKE '%"status": "retry"%'
                OR value_json LIKE '%"status": "running"%')''', (PREFIX+'%',)).fetchone()['n']
            for row in rows:
                if pending >= MAX_JOBS:
                    summary['status'] = 'degraded'
                    summary['reasons']['release_queue_capacity'] = 1
                    break  # Do not advance checkpoint past work not retained.
                source = json.loads(row['body_json'])
                if (row['provider_id'] in approvals and row['active'] and
                        re.search(r'\b(?:earnings|financial results|quarterly results|annual results)\b',
                            str(source.get('title', ''))+' '+str(source.get('source_excerpt', '')), re.I)):
                    try:
                        url = endpoint(source['url'], row['provider_id'])
                    except (KeyError, ValueError):
                        url = None
                    if url:
                        job_key = PREFIX + digest(url)
                        old = _state(c, job_key)
                        if old.get('source_key') != row['source_key']:
                            job = dict(source_key=row['source_key'], source_id=row['source_id'],
                                provider=row['provider_id'], url=url, status='queued', attempts=0,
                                first_seen_at=old.get('first_seen_at', row['collected_at']), next_at=at.isoformat(),
                                previous=old.get('fact') or old.get('previous'))
                            _pending_revision(c, job['previous'], job, at, 'release_revision_pending_verification')
                            _put(c, job_key, job, at)
                            pending += 1
                            summary['discovered'] += 1
                _put(c, CURSOR, dict(collected_at=row['collected_at'], source_key=row['source_key']), at)
            jobs = list(c.execute('''SELECT key,value_json FROM scanner_settings WHERE key LIKE ? AND
                (value_json LIKE '%"status": "queued"%' OR value_json LIKE '%"status": "retry"%'
                OR value_json LIKE '%"status": "running"%')
                ORDER BY updated_at,key LIMIT 2000''', (PREFIX+'%',)).fetchall())
            # Rotate through completed pages separately, so old daily checks
            # cannot hide new/retry work behind a bounded query window.
            done_cursor = _state(c, 'pead_release_completed_rotation_v1').get('key', '')
            done = c.execute('''SELECT key,value_json FROM scanner_settings WHERE key LIKE ?
                AND key>? AND value_json LIKE '%"status": "done"%' ORDER BY key LIMIT 200''',
                (PREFIX+'%', done_cursor)).fetchall()
            if not done and done_cursor:
                done = c.execute('''SELECT key,value_json FROM scanner_settings WHERE key LIKE ?
                    AND value_json LIKE '%"status": "done"%' ORDER BY key LIMIT 200''', (PREFIX+'%',)).fetchall()
            if done:
                _put(c, 'pead_release_completed_rotation_v1', dict(key=done[-1]['key']), at)
            jobs.extend(done)
        ready = []
        for row in jobs:
            job = json.loads(row['value_json'])
            if job['provider'] not in approvals:
                continue
            due = instant(job.get('lease_until') if job['status'] == 'running' else job['next_at'])
            if due <= at:
                ready.append((row['key'], job))
        # Fair due ordering, then immutable source key. Completed pages are
        # revalidated daily for same-URL corrections; no freshness relabeling.
        ready.sort(key=lambda pair: (pair[1]['next_at'], pair[0]))
        for job_key, job in ready[:2]:
            with connect() as c:
                _lock(c)
                current = _state(c, job_key)
                if not _fenced(c, owner, clock()):
                    return dict(summary, status='degraded', reasons={'release_worker_lease_lost': 1})
                if current.get('source_key') != job['source_key']:
                    continue
                circuit = _state(c, 'pead_release_circuit_v1:'+job['provider'])
                if circuit.get('until') and instant(circuit['until']) > at:
                    summary['status'] = 'degraded'
                    summary['reasons']['release_provider_circuit_open'] = 1
                    continue
                withdrawn = c.execute('''SELECT withdrawn_at FROM ne_withdrawals
                    WHERE provider_id=? AND source_id=?''', (job['provider'], job['source_id'])).fetchone()
                if withdrawn:
                    _pending_revision(c, job.get('fact') or job.get('previous'), job, at, 'release_source_withdrawn')
                    _put(c, job_key, dict(job, status='withdrawn', next_at=(at+timedelta(days=1)).isoformat()), at)
                    continue
                _put(c, job_key, dict(job, status='running', owner=owner,
                    lease_until=(at+timedelta(seconds=90)).isoformat()), at)
            try:
                client = transport or Transport(HOSTS[job['provider']], timeout=12, max_bytes=MAX_BODY,
                    user_agent='AI-Trader verified earnings release reader')
                # A nonempty header deliberately disables Transport's automatic
                # redirect branch: a new path is not silently the same source.
                raw = client.request(job['url'], headers={'Accept': 'text/html'})
                observed = instant(clock())
                fact = parse_release(raw, url=job['url'], provider=job['provider'], catalog=catalog,
                    first_seen_at=job['first_seen_at'], observed_at=observed, processed_at=clock(),
                    previous=job.get('fact') or job.get('previous'))
                fact.update(provider_source_id=job['source_id'], source_key=job['source_key'])
                next_at = instant(clock()) + timedelta(days=1)
                # An unchanged page keeps its original availability and does not
                # create a fresh event/revision on daily revalidation/restart.
                prior = job.get('fact')
                if (job['status'] == 'done' and prior and prior.get('verified') is True and
                        fact.get('verified') is True and
                        all(prior.get(key) == fact.get(key) for key in ('document_hash', 'parser_version',
                            'symbol', 'issuer_cik', 'issuer_mapping_hash', 'released_at', 'timing',
                            'timing_verified', 'retracted', 'reasons'))):
                    fact = prior
                with connect() as c:
                    _lock(c)
                    if not _fenced(c, owner, clock(), job_key=job_key, source_key=job['source_key']):
                        return dict(summary, status='degraded', reasons={'release_worker_lease_lost': 1})
                    _record(c, fact)
                    _put(c, job_key, dict(job, status='done', fact=fact, previous=None, attempts=0,
                        next_at=next_at.isoformat()), clock())
                    _put(c, 'pead_release_circuit_v1:'+job['provider'], {}, clock())
                summary['processed'] += 1
                summary['verified' if fact['verified'] else 'unknown'] += 1
                for reason in fact['reasons']:
                    summary['reasons'][reason] = summary['reasons'].get(reason, 0)+1
            except (ProviderFailure, ValueError, OSError) as exc:
                attempt = int(job.get('attempts', 0))+1
                reason = getattr(exc, 'reason', 'release_fetch_failed')
                delay = max(getattr(exc, 'retry_after', 0), min(21600, 300*2**min(attempt, 6)))
                with connect() as c:
                    _lock(c)
                    if not _fenced(c, owner, clock(), job_key=job_key, source_key=job['source_key']):
                        return dict(summary, status='degraded', reasons={'release_worker_lease_lost': 1})
                    _pending_revision(c, job.get('fact') or job.get('previous'), job, clock(), reason)
                    _put(c, job_key, dict(job, status='retry', attempts=attempt, last_error=reason,
                        next_at=(instant(clock())+timedelta(seconds=delay)).isoformat()), clock())
                    if getattr(exc, 'http_status', None) in {403, 429} or attempt >= 3:
                        pause = max(delay, 21600 if getattr(exc, 'http_status', None) == 403 else 900)
                        _put(c, 'pead_release_circuit_v1:'+job['provider'],
                            dict(until=(instant(clock())+timedelta(seconds=pause)).isoformat(), reason=reason), clock())
                summary['status'] = 'degraded'
                summary['reasons'][reason] = summary['reasons'].get(reason, 0)+1
        with connect() as c:
            _lock(c)
            if not _fenced(c, owner, clock()):
                return dict(summary, status='degraded', reasons={'release_worker_lease_lost': 1})
            summary['backlog'] = c.execute('''SELECT COUNT(*) n FROM scanner_settings WHERE key LIKE ?
                AND (value_json LIKE '%"status": "queued"%' OR value_json LIKE '%"status": "retry"%'
                OR value_json LIKE '%"status": "running"%')''', (PREFIX+'%',)).fetchone()['n']
            _put(c, COVERAGE, summary, clock())
        return summary
    finally:
        with connect() as c:
            _lock(c)
            lease = _state(c, 'pead_release_producer_lease_v1')
            if lease.get('owner') == owner:
                _put(c, 'pead_release_producer_lease_v1', dict(owner=owner, until=instant(clock()).isoformat()), clock())


def read_facts(symbols, decision_at, *, connect=None):
    """Bounded as-of projection; latest unknown revisions remain in the stream."""
    from database import get_db_connection
    connect = connect or get_db_connection
    at, symbols = instant(decision_at), set(symbols)
    with connect() as c:
        rows = c.execute('''SELECT metrics_json FROM scanner_candidates WHERE stage='earnings_release'
            AND created_at>=? AND created_at<=? ORDER BY created_at DESC,id DESC LIMIT 4001''',
            ((at-timedelta(days=90)).isoformat(), at.isoformat())).fetchall()
        coverage = _state(c, COVERAGE)
        withdrawals = c.execute('''SELECT provider_id,source_id,withdrawn_at FROM ne_withdrawals
            WHERE withdrawn_at<=? ORDER BY withdrawn_at DESC LIMIT 4001''', (at.isoformat(),)).fetchall()
    if len(rows) > 4000 or len(withdrawals) > 4000:
        return {}, dict(status='unknown', reason='release_projection_capacity', clipped=True)
    withdrawn = {(r['provider_id'], r['source_id']): r['withdrawn_at'] for r in withdrawals}
    result = {}
    for row in rows:
        fact = json.loads(row['metrics_json'])
        if (fact.get('symbol') in symbols and fact.get('released_at') and
                instant(fact['effective_available_at']) <= at):
            withdrawal = withdrawn.get((fact.get('provider'), fact.get('provider_source_id')))
            if withdrawal:
                known = max(instant(withdrawal), instant(fact['effective_available_at']))
                fact = dict(fact, verified=False, retracted=True, reasons=['release_source_withdrawn'],
                    effective_available_at=at.isoformat(), processed_at=at.isoformat(),
                    source_observed_at=known.isoformat(), withdrawn_at=withdrawal)
            result.setdefault(fact['symbol'], []).append(fact)
    # Detector has a 64-event budget. Never truncate a newer correction away.
    for symbol, facts in list(result.items()):
        latest = {}
        for fact in facts:
            latest.setdefault(fact['event_id'], fact)
        if len(latest) > 64:
            result.pop(symbol)
        else:
            result[symbol] = list(latest.values())
    return result, dict(status='ready' if result else 'unknown', source_rows=len(rows),
        reason=None if result else 'verified_release_timing_not_available', producer=coverage,
        coverage='approved_original_wire_pages_not_all_issuers')
