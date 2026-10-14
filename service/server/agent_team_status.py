"""Bounded coordinator reports for the private control room, not worker health.

No jobs, inference, network requests, database writes or agent control. A report
is a dated observation; its presence does not start or keep an agent alive.
"""
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

RUNTIME_REPORT = Path('/app/.runtime/agent-team-status.json')
MAX_BYTES = 32768
ACTIVE_MAX_AGE = 180
ROLES = ('coordinator', 'trading', 'data', 'infrastructure_security', 'ai',
         'ui_telegram', 'independent_qa', 'research_improvements')
STATES = {'queued', 'running', 'completed', 'blocked', 'unknown'}
BLOCKERS = {'needs_approval', 'access_unavailable', 'required_test_failed', 'missing_evidence', 'dependency_pending'}
TASKS = {'coordination', 'trading_correctness', 'data_evidence', 'operations_security',
         'ai_validation', 'mobile_presentation', 'independent_verification', 'improvement_proposals'}
REPORT_URL = re.compile(r'https://github\.com/AviramDahan/AI-Trader/pull/[1-9][0-9]{0,5}\Z')

# Published, completed audit, not a claim about agents running now. The public
# PR is the provenance; no Production rows, private reports or chat IDs bundled.
RELEASE_REPORT = {
    'version': 1, 'run_id': 'audit-pr74', 'reported_at': '2026-10-14T20:45:27Z',
    'report_url': 'https://github.com/AviramDahan/AI-Trader/pull/74',
    'agents': [dict(id=role, state='completed', task=task, observed_at='2026-10-14T20:45:27Z')
               for role, task in zip(ROLES, (
                   'coordination', 'trading_correctness', 'data_evidence', 'operations_security',
                   'ai_validation', 'mobile_presentation', 'independent_verification', 'improvement_proposals'))],
}


def instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('invalid_team_time')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('team_time_requires_utc')
    return result.astimezone(timezone.utc)


def validate(value, now):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('unsupported_team_report')
    run_id = value.get('run_id')
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', run_id):
        raise ValueError('invalid_team_run')
    reported = instant(value.get('reported_at'))
    if (reported-now).total_seconds() > 5:
        raise ValueError('future_team_report')
    url = value.get('report_url')
    if url is not None and (not isinstance(url, str) or not REPORT_URL.fullmatch(url)):
        raise ValueError('invalid_team_provenance')
    rows = value.get('agents')
    if not isinstance(rows, list) or len(rows) > len(ROLES):
        raise ValueError('invalid_team_roles')
    agents, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('id') not in ROLES or row['id'] in seen:
            raise ValueError('invalid_or_duplicate_team_role')
        if row.get('state') not in STATES or row.get('task') not in TASKS:
            raise ValueError('invalid_team_state_or_task')
        blocker = row.get('blocker_code')
        if blocker is not None and (row['state'] != 'blocked' or blocker not in BLOCKERS):
            raise ValueError('invalid_team_blocker')
        at = instant(row.get('observed_at'))
        if at > reported or (at-now).total_seconds() > 5:
            raise ValueError('future_team_observation')
        seen.add(row['id'])
        age = max(0, int((now-at).total_seconds()))
        state = row['state']
        # Completed is explicitly a historical report, not a live green light.
        if state in {'running', 'queued', 'blocked'} and age > ACTIVE_MAX_AGE:
            state = 'stale'
        agents.append({'id': row['id'], 'state': state, 'task': row['task'],
                       'observed_at': at.isoformat(), 'age_seconds': age, 'blocker_code': blocker})
    return {'version': 1, 'run_id': run_id, 'reported_at': reported.isoformat(),
            'report_url': url, 'agents': agents}


def strict_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_team_field')
        value[key] = item
    return value


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('team_report_too_large')
    return json.loads(raw, object_pairs_hook=strict_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_team_value')))


def snapshot(now):
    unknown = {'version': 1, 'source': 'unavailable', 'reason': 'team_report_unavailable',
               'reported_at': None, 'run_id': None, 'report_url': None, 'agents': []}
    try:
        if RUNTIME_REPORT.is_symlink():
            raise ValueError('team_report_symlink')
        try:
            descriptor = os.open(RUNTIME_REPORT, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                                 getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
            with os.fdopen(descriptor, 'rb') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError('team_report_not_regular_file')
                value = decode(handle.read(MAX_BYTES + 1))
            source = 'coordinator_report'
        except FileNotFoundError:
            value, source = RELEASE_REPORT, 'published_audit'
        result = validate(value, now)
        return {**result, 'source': source, 'reason': 'dated_team_report_not_continuous_workers'}
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        # An invalid new report must not revive an older completed/positive one.
        return unknown


def publish(value, now):
    """Explicit coordinator action, operational file only; never called by UI.

    No schema/DB/worker/config/trading mutation. Call only in an approved audit
    workflow. Atomic replacement prevents a half-written report from being read.
    """
    validated = validate(value, now)
    if any(row['state'] == 'stale' for row in validated['agents']):
        raise ValueError('cannot_publish_stale_activity')
    document = {k: validated[k] for k in ('version', 'run_id', 'reported_at', 'report_url')}
    document['agents'] = [{k: row[k] for k in ('id', 'state', 'task', 'observed_at', 'blocker_code')}
                          for row in validated['agents']]
    raw = json.dumps(document, separators=(',', ':')).encode()
    if len(raw) > MAX_BYTES or RUNTIME_REPORT.is_symlink():
        raise ValueError('invalid_team_report_destination')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=RUNTIME_REPORT.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, RUNTIME_REPORT)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return {'published': True, 'agent_count': len(document['agents']),
            'reported_at': document['reported_at']}


if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Validate or explicitly publish a bounded coordinator report from stdin.')
    parser.add_argument('--publish', action='store_true', help='Write the fixed operational report file; never implicit.')
    args = parser.parse_args()
    try:
        now = datetime.now(timezone.utc)
        value = decode(sys.stdin.buffer.read(MAX_BYTES + 1))
        result = publish(value, now) if args.publish else {'valid': bool(validate(value, now))}
        print(json.dumps(result))
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        raise SystemExit('coordinator_report_rejected') from None
