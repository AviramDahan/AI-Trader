"""Filing-backed Telegram notices for ownership and issuer repurchases."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
import re
import unicodedata
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from telegram_topics import SEC_ACTIVITY_EVENT_TYPES, thread_id_for_event


BENEFICIAL_FORMS = {'SCHEDULE 13D', 'SCHEDULE 13D/A', 'SCHEDULE 13G', 'SCHEDULE 13G/A'}


def _number(value):
    if not re.fullmatch(r'\d{1,17}(?:\.\d{1,10})?', str(value)):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and 0 <= result <= Decimal('1e16') else None


def _label(value, limit=120):
    return ' '.join(''.join(c for c in str(value or '') if not unicodedata.category(c).startswith('C')).split())[:limit]


def parse_beneficial_ownership(raw, form, issuer_cik):
    if (form not in BENEFICIAL_FORMS or len(raw) > 2_000_000 or b'\x00' in raw
            or re.search(br'<!\s*(?:DOCTYPE|ENTITY)\b', raw, re.I)):
        raise ValueError('invalid_beneficial_ownership_xml')
    family = form.split()[-1].split('/')[0].lower()
    namespace = '{http://www.sec.gov/edgar/schedule' + family + '}'
    root = ET.fromstring(raw)
    if root.tag != namespace + 'edgarSubmission':
        raise ValueError('unexpected_beneficial_ownership_root')
    for node in root.iter():
        if node.tag.startswith(namespace):
            node.tag = node.tag[len(namespace):]
    if root.findtext('headerData/submissionType', '').strip().upper() != form:
        raise ValueError('beneficial_ownership_form_mismatch')
    header = root.find('formData/coverPageHeader')
    if header is None:
        raise ValueError('missing_ownership_cover_page')
    cik = (header.findtext('issuerInfo/issuerCIK') or header.findtext('issuerInfo/issuerCik') or '').strip()
    if not cik.isascii() or not cik.isdigit() or cik.zfill(10) != issuer_cik:
        raise ValueError('issuer_cik_mismatch')
    is_13d = family == '13d'
    reported = datetime.strptime(header.findtext(
        'dateOfEvent' if is_13d else 'eventDateRequiresFilingThisStatement', '').strip(), '%m/%d/%Y').date()
    path = 'formData/reportingPersons/reportingPersonInfo' if is_13d else 'formData/coverPageHeaderReportingPersonDetails'
    percent_field = 'percentOfClass' if is_13d else 'classPercent'
    persons = []
    for person in root.findall(path):
        name = _label(person.findtext('reportingPersonName'))
        percent = _number(person.findtext(percent_field))
        if name and percent is not None and percent <= 100:
            item = {'name': name, 'percent': _display_number(percent)}
            if item not in persons:
                persons.append(item)
    if not persons:
        raise ValueError('ownership_percent_not_available')
    return {'reported_date': reported.isoformat(), 'security': _label(header.findtext('securitiesClassTitle')),
            'persons': persons[:5], 'additional_person_count': max(0, len(persons) - 5)}


def reported_buyback(payload, job):
    """Select one exact filing's current USD cash-flow period, including YTD."""
    accepted = datetime.fromisoformat(job['accepted_at'].replace('Z', '+00:00')).date()
    if job['form'].endswith('/A'):
        return None  # There is no verified period-to-amendment link in this route.
    rows = payload
    for field in ('facts', 'us-gaap', 'PaymentsForRepurchaseOfCommonStock', 'units', 'USD'):
        rows = rows.get(field) if isinstance(rows, dict) else None
    if not isinstance(rows, list):
        return None
    periods = {}
    for row in rows:
        if not isinstance(row, dict) or row.get('accn') != job['accession'] or row.get('form') != job['form']:
            continue
        try:
            start, end = date.fromisoformat(row['start']), date.fromisoformat(row['end'])
        except (KeyError, ValueError, TypeError):
            continue
        duration = (end - start).days
        valid_duration = 350 <= duration <= 380 if job['form'] == '10-K' else 60 <= duration <= 300
        value = _number(row.get('val'))
        if valid_duration and 0 <= (accepted - end).days <= 120 and value is not None:
            periods.setdefault((end, duration), set()).add(value)
    if not periods:
        return None
    end, duration = max(periods)
    values = periods[(end, duration)]
    if len(values) != 1 or not (value := next(iter(values))):
        return None
    return {'start': (end - timedelta(days=duration)).isoformat(), 'end': end.isoformat(),
            'usd_paid': format(value, 'f')}


def destination(event_type, accepted_at, now):
    from sec_intelligence import killed, mode

    if event_type not in SEC_ACTIVITY_EVENT_TYPES or mode() != 'paper' or killed():
        return None
    if os.getenv('STOCK_SCANNER_TELEGRAM_ENABLED', '').lower() != 'true':
        return None
    try:
        accepted = datetime.fromisoformat(accepted_at.replace('Z', '+00:00'))
        cutoff = datetime.fromisoformat(os.environ['SEC_ACTIVITY_TOPICS_NOT_BEFORE'].replace('Z', '+00:00'))
        hours = min(24, max(1, int(os.getenv('SEC_INTELLIGENCE_PUBLIC_MAX_AGE_HOURS', '6'))))
        if accepted < cutoff or not timedelta(0) <= now - accepted <= timedelta(hours=hours):
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    thread = thread_id_for_event(event_type)
    if thread is not None and any(thread_id_for_event(other) == thread
                                  for other in SEC_ACTIVITY_EVENT_TYPES - {event_type}):
        return None
    return thread


def _display_number(value):
    rendered = format(value, ',f')
    return rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered


def _insider_text(transactions, accepted):
    selected = {}
    for tx in transactions:
        code = tx.get('transaction_code')
        if code not in {'P', 'S'} or tx.get('acquired_disposed') != ('A' if code == 'P' else 'D'):
            continue
        if tx.get('table') != 'non_derivative' or not re.search(
                r'(?:common|ordinary|class [a-z] (?:share|stock))', tx.get('security', ''), re.I):
            continue
        quantity, price = _number(tx.get('shares')), _number(tx.get('price'))
        try:
            traded = date.fromisoformat(tx.get('transaction_at', ''))
        except (ValueError, TypeError):
            continue
        if not quantity or traded > accepted:
            continue
        names = tuple(_label(o.get('name')) for o in tx.get('owners', [])[:3])
        if not any(names):
            continue
        key = (tuple(sorted(o['cik'] for o in tx['owners'])), traded, tx['security'], code, quantity, price)
        selected.setdefault(key, (names, tx.get('plan_10b5_1')))
    lines = []
    for key, (names, plan) in selected.items():
        _, traded, _, code, quantity, price = key
        action = 'רכישה' if code == 'P' else 'מכירה'
        qualifier = ' · תוכנית 10b5-1 דווחה' if plan is True else ''
        price_text = f' במחיר {_display_number(price)} ליחידה' if price else ''
        lines.append(f'• {action} · {traded.isoformat()} · {", ".join(filter(None, names))}\n'
                     f'  {_display_number(quantity)} מניות{price_text}{qualifier}')
    return '\n'.join(lines[:5] + ([f'ועוד {len(lines)-5} עסקאות מדווחות'] if len(lines) > 5 else []))


def enqueue(job, evidence, transactions, now, conn):
    kind = evidence.get('kind')
    event_type = 'buyback_activity' if kind == 'financial' else 'ownership_activity'
    thread = destination(event_type, job['accepted_at'], now)
    if thread is None:
        return False
    accepted = datetime.fromisoformat(job['accepted_at'].replace('Z', '+00:00'))
    if kind == 'ownership' and job['form'] == '4':
        details = _insider_text(transactions, accepted.date())
        heading = '👤 עסקאות בעלי עניין · Form 4'
    elif kind == 'beneficial_ownership':
        holdings = evidence['holdings']
        if date.fromisoformat(holdings['reported_date']) > accepted.date():
            return False
        heading = '🏦 החזקה מדווחת · ' + job['form']
        details = f'תאריך האירוע המדווח {holdings["reported_date"]}\nסוג נייר {holdings["security"]}\n'
        details += '\n'.join(f'• {p["name"]} · {p["percent"]}% מהסוג המדווח' for p in holdings['persons'])
        if holdings['additional_person_count']:
            details += f'\nועוד {holdings["additional_person_count"]} מדווחים'
    elif kind == 'financial' and evidence.get('buyback_cash'):
        from sec_intelligence import _public_compact_usd
        fact = evidence['buyback_cash']
        heading = '🔄 Buyback · תשלומים שבוצעו'
        details = (f'תשלומים לרכישת מניות רגילות עצמיות · {_public_compact_usd(fact["usd_paid"])}\n'
                   f'תקופת הדיווח {fact["start"]} עד {fact["end"]} · {job["form"]}')
    else:
        return False
    if not details:
        return False
    tickers = json.loads(job['tickers_json'])
    universe = conn.execute('SELECT members_json FROM si_universe_snapshots WHERE id=?',
                            (job['universe_snapshot_id'],)).fetchone()
    members = json.loads(universe['members_json']) if universe else {}
    if not tickers or any((members.get(ticker) or {}).get('issuer_cik') != job['issuer_cik'] for ticker in tickers):
        return False
    company = _label(members[tickers[0]].get('company'))
    stamp = accepted.astimezone(ZoneInfo('Asia/Jerusalem')).strftime('%d/%m/%Y %H:%M')
    message = f'{heading}\n\n{company} · {", ".join(tickers[:3])}\n\n{details}\n\nדווח ל־SEC ב־{stamp} (שעון ישראל)'
    payload = json.dumps({'version': 1, 'thread': thread, 'accepted_at': job['accepted_at'], 'text': message})
    if event_type == 'buyback_activity':
        # A later filing can repeat the same reported period and amount.
        key = (f'sec-activity:v1:{event_type}:{job["issuer_cik"]}:'
               f'{fact["start"]}:{fact["end"]}:{_display_number(Decimal(fact["usd_paid"]))}')
    else:
        key = f'sec-activity:v1:{event_type}:{job["accession"]}'
    # A versioned queue state keeps older binaries from claiming this envelope.
    created = now.isoformat().replace('+00:00', 'Z')
    return bool(conn.execute("""INSERT INTO scanner_telegram_outbox
        (dedupe_key,event_type,message,status,attempts,next_attempt_at,created_at)
        VALUES(?,?,?,'sec_topic_pending',0,?,?) ON CONFLICT(dedupe_key) DO NOTHING""",
        (key, event_type, payload, created, created)).rowcount)


def deliver(row, cfg, now, send):
    try:
        payload = json.loads(row['message'])
        thread = destination(row['event_type'], payload['accepted_at'], now)
        if (type(payload.get('version')) is int and payload['version'] == 1 and thread and thread == payload['thread']
                and isinstance(payload['text'], str) and payload['text']
                and cfg.get('telegram_enabled')):
            return send(payload['text'], cfg, row['event_type'])
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return 'sec_activity_unavailable'
