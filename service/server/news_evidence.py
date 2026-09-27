"""Opt-in, SEC-only source enrichment for personal news. No trading writes.

No crawler/search/fuzzy issuer matching. Only an already-ingested exact filing
URL is eligible. SEC explicitly permits reuse of public EDGAR filings; this is
not permission to fetch arbitrary investor-relations websites.
"""
from __future__ import annotations

import hashlib
import html
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from database import get_db_connection
from retry_policy import retry_after

MAX_BYTES = 512 * 1024
MAX_SECONDS = 12
LOCK = threading.Lock()
DNS_LOCK = threading.Lock()
DNS_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sec-evidence-dns')
DNS_PENDING = None
VERSION = 'sec-evidence-v1'


def enabled():
    return os.getenv('NEWS_EVIDENCE_ENABLED', 'false').lower() == 'true'


def stamp(now=None):
    return (now or datetime.now(timezone.utc)).isoformat()


def normalized(text):
    value = re.sub(r'</?[A-Za-z][^>]*>', ' ', str(text or ''))
    return ' '.join(unicodedata.normalize('NFKC', html.unescape(value)).split())


def digest(text):
    return hashlib.sha256(normalized(text).encode()).hexdigest()


def facts(row):
    return json.loads(row.get('source_facts_json') or '{}')


def missing_information(row):
    excerpt = normalized(facts(row).get('source_excerpt'))
    return (not excerpt or excerpt.lower() == normalized(row.get('title')).lower()
            or bool(re.fullmatch(r'(?:PRIMARY DOCUMENT|FORM\s*)?(?:4|144|8-K)?', excerpt, re.I)))


def personal_tickers(row):
    tickers = sorted(set(json.loads(row.get('verified_tickers_json') or '[]')))
    if not tickers:
        return []
    marks = ','.join('?' for _ in tickers)
    with get_db_connection() as c:
        held = c.execute(f"SELECT DISTINCT ticker FROM scanner_trades WHERE status='open' AND remaining_quantity>0 AND is_shadow=0 AND ticker IN ({marks})", tickers).fetchall()
        watched = c.execute(f'SELECT ticker FROM scanner_news_watchlist WHERE enabled=1 AND ticker IN ({marks})', tickers).fetchall()
    return sorted({r['ticker'] for r in [*held, *watched]})


class EvidenceError(ValueError):
    def __init__(self, reason, status=None, delay=0, transient=False):
        self.reason, self.status, self.delay, self.transient = reason, status, delay, transient
        super().__init__('news_evidence_' + reason)


def filing_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != 'www.sec.gov' or p.query or p.fragment
            or '%' in p.path or '\\' in p.path):
        raise EvidenceError('unsafe_url')
    match = re.fullmatch(r'/Archives/edgar/data/(\d{1,10})/(\d{18})/(?:xsl(?:F345X\d+|144X\d+)/)?([A-Za-z0-9_-]+\.(?:xml|htm|html))', p.path)
    if not match:
        raise EvidenceError('unsupported_filing_url')
    return match.group(1).lstrip('0') or '0', match.group(2), p.path


def raw_filing_url(url):
    filing_url(url)
    # SEC's optional stylesheet path renders XML as HTML; the same file under
    # the exact accession directory is the public original structured filing.
    return re.sub(r'/xsl(?:F345X\d+|144X\d+)/', '/', url)


def public_addresses(host):
    global DNS_PENDING
    with DNS_LOCK:
        if DNS_PENDING is not None and not DNS_PENDING.done():
            raise EvidenceError('dns_busy', transient=True)
        DNS_PENDING = DNS_POOL.submit(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
        pending = DNS_PENDING
    try:
        addresses = {entry[4][0] for entry in pending.result(timeout=3)}
    except (FutureTimeout, OSError):
        raise EvidenceError('dns_unavailable', transient=True) from None
    if not addresses or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in addresses):
        raise EvidenceError('non_public_address')
    return sorted(addresses)


class PinnedHTTPS(http.client.HTTPSConnection):
    """TLS still verifies www.sec.gov; connect only to an already-checked IP."""
    def __init__(self, ip, timeout):
        super().__init__('www.sec.gov', timeout=timeout, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        family = socket.AF_INET6 if ':' in self.ip else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect((self.ip, 443))
            self.sock = self._context.wrap_socket(sock, server_hostname='www.sec.gov')
        except BaseException:
            sock.close()
            raise


def fetch_filing(url, user_agent):
    if not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', user_agent or '') or '\n' in user_agent or '\r' in user_agent:
        raise EvidenceError('user_agent_required')
    issuer, accession, _ = filing_url(url)
    url = raw_filing_url(url)
    deadline = time.monotonic() + MAX_SECONDS
    # Share the existing SEC lock/rate limiter; at most one enrichment request
    # per second, well below SEC's 10/s ceiling. No DB transaction during HTTP.
    import news_pipeline
    with news_pipeline.SEC_REQUEST_LOCK:
        for redirect in range(3):
            if filing_url(url)[:2] != (issuer, accession):
                raise EvidenceError('redirect_different_event')
            addresses = public_addresses('www.sec.gov')
            wait = max(0, 1 - (time.monotonic() - news_pipeline.SEC_LAST_REQUEST_AT))
            if time.monotonic() + wait >= deadline:
                raise EvidenceError('deadline', transient=True)
            time.sleep(wait)
            news_pipeline.SEC_LAST_REQUEST_AT = time.monotonic()
            connection = PinnedHTTPS(addresses[0], min(3, deadline - time.monotonic()))
            try:
                connection.request('GET', urlsplit(url).path, headers={
                    'User-Agent': user_agent, 'Accept-Encoding': 'identity',
                    'Accept': 'application/xml,text/xml,text/html'})
                response = connection.getresponse()
                status = response.status
                if status in (301, 302, 303, 307, 308):
                    if redirect == 2:
                        raise EvidenceError('redirect_limit')
                    url = urljoin(url, response.getheader('Location') or '')
                    continue
                if status != 200:
                    raise EvidenceError('http_error', status, retry_after(response.getheader('Retry-After')),
                                        status in (429, 500, 502, 503, 504))
                if response.getheader('Content-Encoding', 'identity') != 'identity':
                    raise EvidenceError('encoded_body')
                media = response.getheader('Content-Type', '').split(';')[0].strip().lower()
                if media not in {'text/html', 'application/xml', 'text/xml', 'text/plain'}:
                    raise EvidenceError('unsupported_media')
                size = response.getheader('Content-Length')
                if size and (not size.isdigit() or int(size) > MAX_BYTES):
                    raise EvidenceError('body_too_large')
                chunks, length = [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise EvidenceError('deadline', transient=True)
                    if connection.sock:
                        connection.sock.settimeout(min(3, remaining))
                    chunk = response.read1(min(8192, MAX_BYTES + 1 - length))
                    if not chunk:
                        break
                    chunks.append(chunk); length += len(chunk)
                    if length > MAX_BYTES:
                        raise EvidenceError('body_too_large')
                return b''.join(chunks).decode('utf-8-sig', errors='strict'), url
            except (OSError, http.client.HTTPException, UnicodeError):
                raise EvidenceError('transport_or_encoding', transient=True) from None
            finally:
                connection.close()
    raise EvidenceError('redirect_limit')


class FilingHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.fields, self.field, self.field_text, self.hidden = [], {}, None, [], 0
        self.has_tables = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table':
            self.has_tables = True
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'ix:nonnumeric' and a.get('name') in ('dei:EntityCentralIndexKey', 'dei:TradingSymbol'):
            self.field = a['name']; self.field_text = []; self.fields.setdefault(self.field, [])
        if tag in ('p', 'div', 'tr', 'br'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'ix:nonnumeric':
            if self.field:
                self.fields[self.field].append(normalized(''.join(self.field_text)))
            self.field = None

    def handle_data(self, data):
        if self.hidden:
            return
        self.parts.append(data)
        if self.field:
            self.field_text.append(data)


def extract(raw, url, verified):
    """Require exact URL accession and document's own issuer identity.

    Form 4 structured fields are source values, not AI interpretation. For an
    inline-XBRL 8-K only complete paragraphs fitting the 2,000-char input budget
    are selected. Unsupported/oversized material stays unavailable, not guessed.
    """
    cik, accession, _ = filing_url(url)
    if '<!ENTITY' in raw.upper() or '<!DOCTYPE' in raw.upper() and url.endswith('.xml'):
        raise EvidenceError('unsafe_xml')
    if url.endswith('.xml'):
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            raise EvidenceError('invalid_xml') from None
        def value(node, path):
            return normalized(node.findtext(path) or '')
        if root.tag != 'ownershipDocument' or value(root, 'documentType') not in ('4', '4/A'):
            raise EvidenceError('unsupported_document')
        issuer = value(root, 'issuer/issuerCik').lstrip('0')
        ticker = value(root, 'issuer/issuerTradingSymbol').upper()
        if issuer != cik or ticker not in verified:
            raise EvidenceError('issuer_mismatch')
        lines = [f"SEC Form {value(root, 'documentType')}; issuer: {value(root, 'issuer/issuerName')}; ticker: {ticker}"]
        lines += [f"Reporting owner: {value(n, 'reportingOwnerId/rptOwnerName')}" for n in root.findall('reportingOwner')]
        for node in root.findall('.//nonDerivativeTransaction') + root.findall('.//derivativeTransaction'):
            fields = [('security', 'securityTitle/value'), ('date', 'transactionDate/value'),
                      ('transaction code', 'transactionCoding/transactionCode'),
                      ('shares', 'transactionAmounts/transactionShares/value'),
                      ('price per share', 'transactionAmounts/transactionPricePerShare/value'),
                      ('acquired/disposed code', 'transactionAmounts/transactionAcquiredDisposedCode/value'),
                      ('shares following transaction', 'postTransactionAmounts/sharesOwnedFollowingTransaction/value')]
            lines.append('; '.join(f'{label}: {value(node, path)}' for label, path in fields))
        lines += [f'Footnote {n.get("id", "")}: {normalized("".join(n.itertext()))}' for n in root.findall('.//footnote')]
        lines += ['Remarks: ' + value(root, 'remarks')] if value(root, 'remarks') else []
        excerpt = '\n'.join(lines)
        if not root.findall('.//nonDerivativeTransaction') and not root.findall('.//derivativeTransaction'):
            raise EvidenceError('no_transaction_facts')
        # Never drop qualifying footnotes/transactions just to fit a prompt.
        if len(excerpt) > 2000:
            raise EvidenceError('excerpt_too_large')
    else:
        parser = FilingHTML(); parser.feed(raw)
        issuers = {v.lstrip('0') for v in parser.fields.get('dei:EntityCentralIndexKey', [])}
        tickers = {v.upper() for v in parser.fields.get('dei:TradingSymbol', [])}
        matched = tickers.intersection(verified)
        if issuers != {cik} or len(matched) != 1:
            raise EvidenceError('issuer_mismatch')
        ticker = matched.pop()
        if parser.has_tables:
            # Flattening financial tables can attach quantities to the wrong
            # headings/periods. Do not feed that ambiguous text to the model.
            raise EvidenceError('tabular_layout_unsupported')
        paragraphs = [normalized(p) for p in ''.join(parser.parts).split('\n') if normalized(p)]
        relevant = []
        for i, p in enumerate(paragraphs):
            if re.match(r'^Item\s+[1-9]\.\d\d\b', p, re.I):
                relevant = paragraphs[i:]; break
        selected = []
        for p in relevant:
            if re.match(r'^(SIGNATURES|EXHIBIT INDEX)$', p, re.I):
                break
            if sum(len(v) + 1 for v in selected) + len(p) > 1850:
                break
            selected.append(p)
        excerpt = f'SEC filing excerpt only; issuer CIK {cik}; ticker {ticker}\n' + '\n'.join(selected)
        if len(' '.join(selected).split()) < 25:
            raise EvidenceError('insufficient_excerpt')
    return dict(issuer_cik=cik, ticker=ticker, accession=accession, selected_excerpt=excerpt,
                content_version=digest(excerpt))


def prepare(row, now=None, fetcher=None):
    """In-memory overlay only. Does NOT update scanner_news/source caches."""
    now = now or datetime.now(timezone.utc)
    copy = dict(row)
    if not missing_information(row) or row.get('provider') != 'sec_edgar':
        return copy
    verified = personal_tickers(row)
    if not verified:
        return copy
    # Activation fence is explicit. Enriching old history must never make it
    # eligible for a public replay. Offline replay can call extract directly.
    try:
        fence = datetime.fromisoformat(os.environ['NEWS_EVIDENCE_NOT_BEFORE'].replace('Z', '+00:00'))
        published = datetime.fromisoformat(row['published_at'].replace('Z', '+00:00'))
        if published < fence or published > now + timedelta(minutes=10):
            copy['_evidence_reason'] = 'outside_activation_window'
            return copy
    except (KeyError, ValueError, TypeError):
        copy['_evidence_reason'] = 'activation_fence_required'
        return copy
    try:
        cik, accession, _ = filing_url(row['url'])
        if row.get('canonical_key') not in (None, '', 'sec:' + accession,
                'sec:' + accession[:10] + '-' + accession[10:12] + '-' + accession[12:]):
            raise EvidenceError('event_mismatch')
    except EvidenceError as exc:
        copy['_evidence_reason'] = exc.reason
        copy['_evidence_terminal'] = True
        copy['_evidence_retry_after'] = 0
        return copy
    key = digest(row['url'] + '|' + ','.join(verified))
    copy['_evidence_key'] = key
    with LOCK:
        with get_db_connection() as c:
            cached = c.execute('SELECT * FROM news_evidence WHERE cache_key=?', (key,)).fetchone()
            previous = c.execute('SELECT * FROM news_evidence_attempts WHERE cache_key=?', (key,)).fetchone()
            provider_pause = c.execute("SELECT * FROM news_evidence_attempts WHERE cache_key='provider:sec_evidence'").fetchone()
        if cached:
            data = dict(cached)
        elif previous and (previous['status'] == 'terminal' or datetime.fromisoformat(previous['next_attempt_at']) > now):
            copy['_evidence_reason'] = previous['reason']
            copy['_evidence_terminal'] = previous['status'] == 'terminal'
            copy['_evidence_retry_after'] = max(0, (datetime.fromisoformat(previous['next_attempt_at']) - now).total_seconds())
            return copy
        else:
            if provider_pause and datetime.fromisoformat(provider_pause['next_attempt_at']) > now:
                copy.update(_evidence_reason='provider_backoff', _evidence_terminal=False,
                            _evidence_retry_after=(datetime.fromisoformat(provider_pause['next_attempt_at'])-now).total_seconds())
                return copy
            attempts = (previous['attempts'] if previous else 0) + 1
            try:
                raw, final_url = (fetcher or fetch_filing)(row['url'], os.getenv('NEWS_SEC_USER_AGENT', ''))
                data = dict(cache_key=key, source_url=final_url, source_published_at=row['published_at'],
                            collected_at=stamp(now), raw_source_text=raw, **extract(raw, final_url, verified))
                with get_db_connection() as c:
                    c.execute('''INSERT INTO news_evidence(cache_key,source_url,source_published_at,collected_at,
                        content_version,raw_source_text,selected_excerpt,issuer_cik,ticker,accession)
                        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO NOTHING''',
                        tuple(data[k] for k in ('cache_key','source_url','source_published_at','collected_at',
                        'content_version','raw_source_text','selected_excerpt','issuer_cik','ticker','accession')))
            except EvidenceError as exc:
                delay = max(exc.delay, 60 * 2 ** (attempts - 1))
                state = 'retry' if exc.transient and attempts < 3 else 'terminal'
                with get_db_connection() as c:
                    c.execute('''INSERT INTO news_evidence_attempts(cache_key,attempts,status,reason,http_status,next_attempt_at,updated_at)
                        VALUES(?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET attempts=excluded.attempts,
                        status=excluded.status,reason=excluded.reason,http_status=excluded.http_status,
                        next_attempt_at=excluded.next_attempt_at,updated_at=excluded.updated_at''',
                        (key, attempts, state, exc.reason, exc.status, stamp(now + timedelta(seconds=delay)), stamp(now)))
                    if exc.transient and (exc.status == 429 or exc.delay > 0):
                        c.execute('''INSERT INTO news_evidence_attempts(cache_key,attempts,status,reason,http_status,next_attempt_at,updated_at)
                            VALUES('provider:sec_evidence',0,'retry','provider_backoff',?,?,?)
                            ON CONFLICT(cache_key) DO UPDATE SET http_status=excluded.http_status,
                            next_attempt_at=excluded.next_attempt_at,updated_at=excluded.updated_at''',
                            (exc.status, stamp(now + timedelta(seconds=delay)), stamp(now)))
                copy['_evidence_reason'] = exc.reason
                copy['_evidence_terminal'] = state == 'terminal'
                copy['_evidence_retry_after'] = delay
                return copy
        copy['source_facts_json'] = json.dumps({**facts(row), 'source_excerpt': data['selected_excerpt']}, ensure_ascii=False)
        copy['_evidence_key'] = key
        copy['_evidence_version'] = data['content_version']
        copy['_evidence_source'] = {k: data[k] for k in ('source_url','source_published_at','collected_at','content_version')}
        return copy


def review(row, analyzer):
    if not enabled():
        return analyzer(row)
    prepared = prepare(row)
    if '_evidence_terminal' in prepared:
        return dict(id=row['id'], _error=('news_evidence_unavailable' if prepared['_evidence_terminal'] else 'news_evidence_pending')+':'+prepared['_evidence_reason'],
                    _retry_after=prepared['_evidence_retry_after'], _evidence_reason=prepared['_evidence_reason'],
                    _evidence_key=prepared.get('_evidence_key'))
    excerpt = str(facts(prepared).get('source_excerpt') or '')[:2000]
    version = digest(normalized(row['title']) + '\n' + normalized(excerpt))
    meta = dict(_news_version=version, _evidence_key=prepared.get('_evidence_key'),
                _missing_information=missing_information(prepared), _evidence_reason=prepared.get('_evidence_reason'))
    def terminal_error(reason):
        error = ValueError(reason)
        error.news_evidence_meta = meta
        return error
    # A date/format change never starts a new analysis. Model/prompt/thesis and
    # routing context changes may require a fresh assessment, not fresh facts.
    key = digest('|'.join((VERSION, str(row['id']), version, str(row.get('thesis') or ''),
                         str(row.get('scope') or ''), str(row.get('verified_tickers_json') or ''),
                         os.getenv('OPENROUTER_NEWS_MODEL', os.getenv('OPENROUTER_MODEL', '')))))
    terminal_key = digest('|'.join((VERSION, 'terminal-quality', version,
                         os.getenv('OPENROUTER_NEWS_MODEL', os.getenv('OPENROUTER_MODEL', '')))))
    with get_db_connection() as c:
        terminal = c.execute('SELECT terminal_error FROM news_review_cache WHERE cache_key=?', (terminal_key,)).fetchone()
        cached = c.execute('SELECT * FROM news_review_cache WHERE cache_key=?', (key,)).fetchone()
    if terminal and terminal['terminal_error']:
        raise terminal_error(terminal['terminal_error'])
    if cached:
        if cached['terminal_error']:
            raise terminal_error(cached['terminal_error'])
        result = json.loads(cached['result_json'])
    else:
        from news_call_context import article
        try:
            with article(row['id'], version, excerpt):
                result = analyzer(prepared)
        except ValueError as exc:
            exc.news_evidence_meta = meta
            # Store only allowlisted deterministic failures, never model/source
            # text, HTTP bodies, tokens or free-form exception strings.
            reason = str(exc).split(':')[0]
            if reason in ('news_quality_rejected', 'news_missing_hebrew'):
                with get_db_connection() as c:
                    c.execute('''INSERT INTO news_review_cache(cache_key,content_version,terminal_error,created_at)
                        VALUES(?,?,?,?) ON CONFLICT(cache_key) DO NOTHING''', (terminal_key, version, reason, stamp()))
            raise
        with get_db_connection() as c:
            c.execute('''INSERT INTO news_review_cache(cache_key,content_version,result_json,created_at)
                VALUES(?,?,?,?) ON CONFLICT(cache_key) DO NOTHING''', (key, version, json.dumps(result, ensure_ascii=False), stamp()))
    return {**result, **meta}


def audit(cur, row, result, reason=None, at=None):
    if not enabled():
        return
    reasons = []
    if reason:
        reasons.append(reason)
    elif result.get('duplicate_of'):
        reasons.append('duplicate')
    elif not result.get('related'):
        reasons.append('irrelevant')
    elif result.get('materiality') == 'low':
        reasons.append('insufficient_information' if result.get('_missing_information', missing_information(row)) else 'low_importance')
    elif result.get('relevance', 0) < __import__('news_pipeline').feed_settings()['alert_min_relevance']:
        reasons.append('irrelevant')
    elif result.get('sentiment') in ('unclear', 'neutral'):
        reasons.append('no_directional_impact')
    cur.execute('''INSERT INTO news_publication_audit(news_id,content_version,evidence_key,reasons_json,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(news_id) DO UPDATE SET content_version=excluded.content_version,
        evidence_key=excluded.evidence_key,reasons_json=excluded.reasons_json,updated_at=excluded.updated_at''',
        (row['id'], result.get('_news_version') or row.get('content_hash') or '',
         result.get('_evidence_key'), json.dumps(reasons), at or stamp()))


def decorate(cur, item):
    # Preserve provenance of already-reviewed items after the kill switch is
    # turned off. Disabling collection must not mislabel their source evidence.
    info = cur.execute('SELECT * FROM news_publication_audit WHERE news_id=?', (item['id'],)).fetchone()
    if info:
        item['publication_reasons'] = json.loads(info['reasons_json'])
        if info['evidence_key']:
            evidence = cur.execute('''SELECT source_url,source_published_at,collected_at,content_version
                FROM news_evidence WHERE cache_key=?''', (info['evidence_key'],)).fetchone()
            if evidence:
                item['source_enrichment'] = dict(evidence)
            else:
                attempt = cur.execute('''SELECT attempts,status,reason,http_status,next_attempt_at,updated_at
                    FROM news_evidence_attempts WHERE cache_key=?''', (info['evidence_key'],)).fetchone()
                if attempt:
                    item['source_enrichment_status'] = dict(attempt)
    return item


def source_limit(row):
    if row.get('source_enrichment'):
        return 'נותח קטע מאומת של אותו דיווח SEC; לא הכתבה המלאה. זמן הפרסום המקורי נשמר.'
    return 'זמינים כותרת ומטא־דאטה בלבד.' if row.get('headline_only') else 'זמין תקציר שסופק בפיד; הכתבה המלאה לא נותחה.'


def needs_personal_route(cur, row, duplicate_id):
    """A broad-topic duplicate does not prove delivery to a personal recipient."""
    if not enabled():
        return False
    for ticker in json.loads(row.get('verified_tickers_json') or '[]'):
        held = cur.execute("SELECT id FROM scanner_trades WHERE ticker=? AND status='open' AND remaining_quantity>0 AND is_shadow=0", (ticker,)).fetchall()
        watched = cur.execute('SELECT 1 FROM scanner_news_watchlist WHERE ticker=? AND enabled=1', (ticker,)).fetchone()
        for trade in held:
            seen = cur.execute('SELECT 1 FROM scanner_news_alerts WHERE news_id=? AND trade_id=?', (duplicate_id, trade['id'])).fetchone()
            if not seen:
                return True
        if watched and not held:
            seen = cur.execute('SELECT 1 FROM scanner_news_watchlist_alerts WHERE news_id=? AND ticker=?', (duplicate_id, ticker)).fetchone()
            if not seen:
                return True
    return False


def publication_outcome(cur, row, result, queued, at):
    if not enabled():
        return
    if queued:
        audit(cur, row, result, reason='queued', at=at)
        # queued is an operational state, not a reason for nonpublication.
        cur.execute("UPDATE news_publication_audit SET reasons_json='[]' WHERE news_id=?", (row['id'],))
        return
    info = cur.execute('SELECT reasons_json FROM news_publication_audit WHERE news_id=?', (row['id'],)).fetchone()
    if info and json.loads(info['reasons_json']):
        return
    fence = os.getenv('TELEGRAM_NEWS_NOT_BEFORE')
    if fence and datetime.fromisoformat(row['published_at'].replace('Z','+00:00')) < datetime.fromisoformat(fence.replace('Z','+00:00')):
        reason = 'backlog_blocked'
    else:
        from news_pipeline import _same_event_filter, feed_settings
        clause, values = _same_event_filter('seen', row)
        matches = sum(bool(cur.execute(f'SELECT 1 FROM {table} a JOIN scanner_news seen ON seen.id=a.news_id WHERE ({clause}) LIMIT 1', values).fetchone())
                      for table in ('scanner_news_alerts','scanner_news_watchlist_alerts','scanner_news_broadcast_alerts'))
        if matches:
            reason = 'duplicate'
        elif (result.get('materiality') != 'high' or result.get('relevance',0) < feed_settings()['broad_alert_min_relevance']):
            reason = 'below_broad_threshold'
        else:
            reason = 'routing_failure'
    audit(cur, row, result, reason=reason, at=at)
