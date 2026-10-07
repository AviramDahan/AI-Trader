"""Observations only: never an input to trading, AI, sizing or routing.

Stored in the existing candidate journal, status=observed (not rejected), so
existing rejection counts and the recovery snapshot contract remain unchanged.
"""
import hashlib
import json
import logging
import math
import os
from datetime import datetime, timezone

LOG = logging.getLogger(__name__)
VERSION = 1
MAX_BYTES = 65536


def _source(source):
    return {'atr': source.get('atr'), 'data_as_of': source.get('data_as_of'),
            'zones': [{k: z[k] for k in ('low', 'high', 'touches') if k in z} |
                      {'pivots': [{k: p[k] for k in ('price', 'date', 'kind', 'confirmed_at') if k in p}
                                  for p in z.get('pivots', [])]} for z in source.get('zones', [])]}


def _geometry(entry, source):
    """Diagnostic arithmetic only; policy.build remains the sole decision maker."""
    atr, zones = source['atr'], source['zones']
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (entry, atr)):
        return {'detail': 'invalid_numeric_input'}
    ahead = sorted((z for z in zones if z['low'] > entry), key=lambda z: z['low'])
    behind = [z for z in zones if z['high'] < entry]
    out = {'entry_inside_zone': any(z['low'] <= entry <= z['high'] for z in zones),
           'nearest_resistance': ahead[0] if ahead else None,
           'stop_anchor': max(behind, key=lambda z: z['high']) if behind else None}
    if not ahead or not behind:
        return out
    risk = max(entry - (out['stop_anchor']['low'] - .25 * atr), 1.5 * atr, .01 * entry)
    raw_stop, raw_target = entry - risk, ahead[0]['low'] - .15 * atr
    stop, target = round(raw_stop, 2), round(raw_target, 2)
    conditions = []
    if stop <= 0: conditions.append('non_positive_stop')
    if stop >= entry: conditions.append('stop_not_below_entry')
    if target <= entry:
        conditions.append('target_buffer_reaches_entry' if raw_target <= entry else 'target_rounds_to_or_below_entry')
    if target >= ahead[0]['low']: conditions.append('rounded_target_not_before_resistance')
    out.update(stop_unrounded=raw_stop, stop_rounded=stop, target_unrounded=raw_target,
               target_rounded=target, rr_unrounded=(raw_target-entry)/risk,
               rr_rounded=(target-entry)/(entry-stop) if entry > stop else None,
               invalid_level_conditions=conditions)
    return out


def capture(candidate, action, price, quote_at, phase, policy, strategy, source, cfg,
            *, decided_at, plan=None, rejection=None, evaluated=True):
    """Best effort, bounded, allowlisted; must not change caller returns/errors."""
    try:
        import final_ai
        trace = final_ai.TRACE.get()
        if trace is None:
            return
        trace['target_evidence_attempted'] = True
        inputs = _source(source)
        record = dict(evidence_version=VERSION, observation_id=trace['id']+':'+phase,
                      review_id=trace['id'], scan_id=trace['scan_id'], ticker=trace['ticker'],
                      company=str(candidate.get('company') or '')[:160], phase=phase,
                      build_sha=os.getenv('BUILD_SHA'), policy_version=policy, strategy=strategy,
                      action=action, observed_at=datetime.now(timezone.utc).isoformat(),
                      decided_at=decided_at, evaluated=evaluated, outcome='PASS' if evaluated and plan else
                      'REJECT' if evaluated else 'NOT_EVALUATED', rejection_reason=rejection,
                      quote={'price':price,'as_of':quote_at,'source':'yahoo_1m_close' if quote_at else None,
                             'provenance_status':'RECORDED' if quote_at else 'NOT_AVAILABLE'},
                      source_inputs=inputs, source_inputs_sha256=hashlib.sha256(
                          json.dumps(inputs, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                      minimum_rr=2.0 if policy=='single_target_v2' else cfg.get('min_risk_reward'),
                      signal_link={'scan_id':trace['scan_id'],'ticker':trace['ticker']})
        reference = candidate.get('_reference_context')
        if reference:
            record['quote'].update({k:reference[k] for k in ('source','fresh','age_seconds','eligible_for_entry')})
        record['source_observed_at'] = candidate.get('history_fetched_at')
        if policy == 'single_target_v2' and evaluated:
            record['geometry'] = _geometry(price, inputs)
            if rejection == 'invalid_rounded_levels':
                record['rejection_detail'] = record['geometry'].get('invalid_level_conditions', [])
        if plan:
            record['accepted_levels'] = {k:plan[k] for k in ('entry','stop','targets','active_target','rr') if k in plan}
        encoded = json.dumps(record, allow_nan=False)
        if len(encoded.encode()) > MAX_BYTES:
            record = {k:record[k] for k in ('evidence_version','observation_id','review_id','scan_id','ticker',
                      'phase','build_sha','policy_version','outcome','rejection_reason','observed_at','decided_at','quote','source_inputs_sha256')}
            record['evidence_gap'] = 'payload_exceeds_64k_no_full_replay'
        # JSON round trip freezes a copy; subsequent candidate/plan edits cannot rewrite evidence.
        trace.setdefault('target_checks', {})[phase] = json.loads(json.dumps(record, allow_nan=False))
    except Exception as exc:
        LOG.warning('target_evidence_capture_failed:%s', type(exc).__name__)


def persist_checks(conn, trace):
    """Inside final_ai.persist's transaction, AFTER its unique review-row upsert.

    That row serializes concurrent same-review writers in PostgreSQL. SQLite's
    write transaction does the same. A savepoint isolates evidence failures.
    No extra HTTP, AI attempt, signal, order, or message can originate here.
    """
    checks = trace.get('target_checks')
    if not checks:
        return
    conn.execute('SAVEPOINT target_evidence')
    try:
        existing = conn.execute("SELECT metrics_json FROM scanner_candidates WHERE scan_id=? AND ticker=? AND stage='target_check'",
                                (trace['scan_id'],trace['ticker'])).fetchall()
        seen = {json.loads(r['metrics_json']).get('observation_id') for r in existing}
        for r in checks.values():
            if r['observation_id'] in seen:
                continue
            conn.execute("""INSERT INTO scanner_candidates(scan_id,ticker,company,stage,status,reason,metrics_json,created_at)
                VALUES(?,?,?,'target_check','observed',?,?,?)""",
                (trace['scan_id'],trace['ticker'],r.get('company'),r.get('rejection_reason'),
                 json.dumps(r, allow_nan=False),r['observed_at']))
            seen.add(r['observation_id'])
    except Exception as exc:
        conn.execute('ROLLBACK TO SAVEPOINT target_evidence')
        LOG.warning('target_evidence_persist_failed:%s', type(exc).__name__)
    finally:
        conn.execute('RELEASE SAVEPOINT target_evidence')


def persist_decision(conn, trace):
    decision = trace.get('decision')
    if not decision:
        return
    conn.execute('SAVEPOINT ai_decision_evidence')
    try:
        observation_id = trace['id'] + ':ai_decision'
        rows = conn.execute("SELECT metrics_json FROM scanner_candidates WHERE scan_id=? AND ticker=? AND stage='ai_decision'",
            (trace['scan_id'], trace['ticker'])).fetchall()
        if any(json.loads(row['metrics_json']).get('observation_id') == observation_id for row in rows):
            return
        allowed = {k:decision[k] for k in ('action','confidence','news_sentiment','news_relevance',
            'filter_failures','confidence_threshold','relevance_threshold','quote',
            'daily_reference_close','daily_reference_as_of') if k in decision}
        allowed['observation_id'] = observation_id
        conn.execute("""INSERT INTO scanner_candidates(scan_id,ticker,company,stage,status,reason,metrics_json,created_at)
            VALUES(?,?,NULL,'ai_decision','observed',NULL,?,?)""",
            (trace['scan_id'], trace['ticker'], json.dumps(allowed, allow_nan=False), datetime.now(timezone.utc).isoformat()))
    except Exception as exc:
        conn.execute('ROLLBACK TO SAVEPOINT ai_decision_evidence')
        LOG.warning('ai_decision_evidence_persist_failed:%s', type(exc).__name__)
    finally:
        conn.execute('RELEASE SAVEPOINT ai_decision_evidence')
