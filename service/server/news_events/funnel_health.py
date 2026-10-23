"""Bounded news throughput evidence, not trading policy or a publication quota.

One event-created cohort and current evidence versions. Window deliveries are
separate: a late notice about an older event cannot certify new-cohort success.
Only SELECTs (and transaction guards) run here; there are no producer/AI/sender
calls, automatic retries, failbacks, or per-event/history payloads.
"""
from datetime import datetime, timedelta
from .model import timestamp

STATES = {'observed', 'no_input', 'review_required', 'unknown'}
ADVISORIES = {'high_preanalysis_loss_no_routing', 'no_publication_with_input'}
COUNTS = ('events', 'identity_unverified', 'insufficient_information',
          'other_precheck_blocked', 'quality_failed', 'pending', 'analyzing',
          'current_analysis_done', 'current_analysis_failed', 'routed_events',
          'cohort_sent_events', 'sent_window_notices')
NEWS_KINDS = "('market_news','stock_news','position_news','watchlist_news')"


def unavailable():
    return {'version': 1, 'status': 'unknown', 'checked_at': None,
            'window_start': None, 'window_end': None, 'counts': None,
            'preanalysis_loss_ratio': None, 'advisories': [],
            'cohort_basis': 'event_created_at_current_evidence_version',
            'interpretation': 'missing_evidence_not_zero_or_success'}


def snapshot(c, current, not_before=None):
    """Use a fresh connection. PostgreSQL guards affect only this read transaction.

    Observation failures stay UNKNOWN; never retry without bounds or interfere
    with the separate integrity/safety checks or active news/trading workers.
    """
    try:
        end = datetime.fromisoformat(timestamp(current))
        start = end - timedelta(hours=6)
        if not_before is not None:
            start = max(start, datetime.fromisoformat(timestamp(not_before)))
        if start > end:
            return unavailable()
        if getattr(c, '_backend', 'sqlite') == 'postgres':
            c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            c.execute("SET LOCAL statement_timeout='5s'")
            c.execute("SET LOCAL lock_timeout='2s'")
            if c.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] != 'on':
                return unavailable()
            if c.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] != 'repeatable read':
                return unavailable()
        bounds = (timestamp(start), timestamp(end))
        groups = c.execute('''SELECT status,reason,count(*) n,min(created_at) oldest
            FROM ne_events WHERE created_at>=? AND created_at<?
            GROUP BY status,reason LIMIT 129''', bounds).fetchall()
        if len(groups) > 128:
            return unavailable()  # Never label a truncated observation healthy.
        counts = {k: 0 for k in COUNTS}
        oldest = None
        for row in groups:
            n = row['n']
            if type(n) is not int or n < 0 or row['status'] not in {
                    'blocked','pending','analyzing','analyzed','quality_failed','needs_material_review'}:
                return unavailable()
            counts['events'] += n
            at = datetime.fromisoformat(timestamp(row['oldest']))
            oldest = min(oldest, at) if oldest else at
            if row['status'] == 'blocked':
                code = row['reason'] if row['reason'] in {
                    'identity_unverified', 'insufficient_information'} else 'other_precheck_blocked'
                counts[code] += n
            elif row['status'] in {'quality_failed', 'pending', 'analyzing'}:
                counts[row['status']] += n
        stats = c.execute('''SELECT
            coalesce(sum(CASE WHEN EXISTS(SELECT 1 FROM ne_analysis a WHERE
                a.event_id=e.event_id AND a.version=e.evidence_version AND a.status='done') THEN 1 ELSE 0 END),0) current_analysis_done,
            coalesce(sum(CASE WHEN EXISTS(SELECT 1 FROM ne_analysis a WHERE
                a.event_id=e.event_id AND a.version=e.evidence_version AND a.status='failed') THEN 1 ELSE 0 END),0) current_analysis_failed,
            coalesce(sum(CASE WHEN EXISTS(SELECT 1 FROM ne_delivery d WHERE
                d.event_id=e.event_id AND d.version=e.evidence_version AND d.status IN ('outbox','legacy_receipt')) THEN 1 ELSE 0 END),0) routed_events,
            coalesce(sum(CASE WHEN EXISTS(SELECT 1 FROM ne_outbox link JOIN scanner_telegram_outbox o ON
                o.dedupe_key=link.dedupe_key WHERE link.event_id=e.event_id AND link.version=e.evidence_version
                AND o.status='sent') THEN 1 ELSE 0 END),0) cohort_sent_events
            FROM ne_events e WHERE e.created_at>=? AND e.created_at<?''', bounds).fetchone()
        for key in ('current_analysis_done','current_analysis_failed','routed_events','cohort_sent_events'):
            counts[key] = int(stats[key])
        sent = c.execute(f'''SELECT count(*) n,max(o.sent_at) latest FROM scanner_telegram_outbox o
            JOIN ne_outbox link ON link.dedupe_key=o.dedupe_key
            WHERE o.status='sent' AND o.event_type IN {NEWS_KINDS} AND o.sent_at>=? AND o.sent_at<?''', bounds).fetchone()
        counts['sent_window_notices'] = int(sent['n'])
        loss = counts['identity_unverified'] + counts['insufficient_information']
        ratio = loss / counts['events'] if counts['events'] else None
        observed_age = (end-oldest).total_seconds() if oldest else 0
        advisories = []
        # Operational review triggers ONLY. They do not declare every blocked
        # event erroneous, demand news volume, change eligibility or spend AI.
        if counts['events'] >= 50 and observed_age >= 3600:
            if ratio >= .8 and not counts['routed_events']:
                advisories.append('high_preanalysis_loss_no_routing')
            if observed_age >= 10800 and not counts['sent_window_notices']:
                advisories.append('no_publication_with_input')
        return {'version': 1, 'status': 'review_required' if advisories else
                'observed' if counts['events'] else 'no_input',
                'checked_at': timestamp(end), 'window_start': timestamp(start),
                'window_end': timestamp(end), 'counts': counts,
                'preanalysis_loss_ratio': ratio, 'advisories': advisories,
                'latest_sent_in_window': sent['latest'],
                'cohort_basis': 'event_created_at_current_evidence_version',
                'interpretation': 'review_trigger_not_a_bug_or_publication_quota'}
    except Exception:
        # No database/exception text, article, identifier, prompt or secret.
        return unavailable()


def projection(value, current):
    """Strict private UI projection; stale or malformed evidence never turns green."""
    try:
        if not isinstance(value, dict) or type(value.get('version')) is not int or value.get('version') != 1 or value.get('status') not in STATES-{'unknown'}:
            return unavailable()
        now = datetime.fromisoformat(timestamp(current))
        at = datetime.fromisoformat(timestamp(value['checked_at']))
        if not -5 <= (now-at).total_seconds() <= 180:
            return unavailable()
        start = datetime.fromisoformat(timestamp(value['window_start']))
        end = datetime.fromisoformat(timestamp(value['window_end']))
        if not start <= end == at or (end-start).total_seconds() > 21600:
            return unavailable()
        raw = value['counts']
        if not isinstance(raw, dict) or any(type(raw.get(k)) is not int or not 0 <= raw[k] <= 10**9 for k in COUNTS):
            return unavailable()
        total = raw['events']
        if any(raw[k] > total for k in COUNTS if k not in {'events','sent_window_notices'}):
            return unavailable()
        if (sum(raw[k] for k in ('identity_unverified','insufficient_information',
                'other_precheck_blocked','quality_failed','pending','analyzing')) > total
                or raw['current_analysis_done']+raw['current_analysis_failed'] > total
                or (value['status'] == 'no_input') != (total == 0)):
            return unavailable()
        notes = value['advisories']
        if (not isinstance(notes, list) or any(n not in ADVISORIES for n in notes)
                or bool(notes) != (value['status'] == 'review_required')):
            return unavailable()
        return {'version': 1, 'status': value['status'], 'checked_at': timestamp(at),
                'window_start': timestamp(start), 'window_end': timestamp(end),
                'counts': {k: raw[k] for k in COUNTS}, 'advisories': sorted(set(notes)),
                'cohort_basis': 'event_created_at_current_evidence_version'}
    except (ValueError, TypeError, KeyError, OverflowError):
        return unavailable()


def summary(value):
    if value.get('status') == 'unknown':
        return 'משפך חדשות: אין תצפית תקפה; לא אומתה תפוקת פרסום'
    counts = value['counts']
    state = {'review_required': 'נדרשת בדיקה', 'no_input': 'לא נצפה קלט חדש',
             'observed': 'נמדד; לא אישור איכות או כיסוי מלא'}[value['status']]
    return ('משפך חדשות — '+state+'\nחלון עד 6 שעות, אירועים חדשים: '+str(counts['events'])+
            '; חסימת זיהוי: '+str(counts['identity_unverified'])+
            '; מידע חסר: '+str(counts['insufficient_information'])+
            '; נותבו מהקבוצה: '+str(counts['routed_events'])+
            '; נשלחו מהקבוצה: '+str(counts['cohort_sent_events'])+
            '\nהודעות קנוניות שנשלחו בחלון (כולל אירועים ישנים): '+str(counts['sent_window_notices']))
