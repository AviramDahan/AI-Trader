"""Bounded audit-query/decoding regressions; no provider, worker or live DB."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entry_repair_audit import collect
from test_single_target_v2 import zone


def check(**changes):
    return dict(phase='pre_ai', action='BUY', evaluated=True, ticker='TEST',
                source_inputs=dict(atr=1, zones=[zone(98, 98.4)], data_as_of='2026-09-25'),
                source_inputs_sha256='synthetic-source', quote=dict(price=100),
                decided_at='2026-10-06T14:00:00Z', **changes)


class Result:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return self.rows[0]
    def fetchall(self): return self.rows
    def __iter__(self): return iter(self.rows)


class AuditConnection:
    def __init__(self, targets, technical=()):
        self.targets, self.technical, self.queries = targets, list(technical), []

    def execute(self, query, params=()):
        self.queries.append((query, params))
        assert 'LATERAL' not in query, 'Per-observation correlated scans are forbidden'
        assert not any(word in query.upper().split() for word in ('INSERT', 'UPDATE', 'DELETE'))
        if 'SHOW transaction_read_only' in query:
            return Result([dict(transaction_read_only='on')])
        if 'DISTINCT ON' in query:
            return Result(self.technical)
        if 'scanner_candidates' in query:
            return Result(self.targets)
        if 'SELECT count(*) count' in query:
            return Result([dict(count=0)])
        return Result([])


def target(value, n=1):
    return dict(id=n, scan_id='scan', ticker='TEST', metrics_json=json.dumps(value))


def test_audit_uses_one_bounded_batch_not_per_observation_lookup():
    c = AuditConnection([target(check(), n) for n in range(1, 51)],
                        [dict(scan_id='scan', ticker='TEST', metrics_json='{"recent_high_20d":99}')])
    report = collect(c, '2026-10-01T00:00:00Z')
    assert report['paired_structural_checks'] == {'BASELINE_FAIL_NEW_PASS': 50}
    assert report['unique_ticker_source_structures'] == 1
    lookups = [(sql, args) for sql, args in c.queries if 'DISTINCT ON' in sql]
    assert len(lookups) == 1 and lookups[0][1] == ('scan', 'TEST')
    assert 'LIMIT 2001' in c.queries[1][0]


def test_empty_evaluated_cohort_does_not_query_technical_population():
    c = AuditConnection([])
    assert collect(c, '2026-10-01T00:00:00Z')['paired_structural_checks'] == {}
    assert not any('DISTINCT ON' in sql for sql, _ in c.queries)


def test_bad_target_or_technical_evidence_is_unknown_not_a_pass():
    bad = target(check()); bad['metrics_json'] = '{invalid'
    c = AuditConnection([bad, target(check(), 2)],
                        [dict(scan_id='scan', ticker='TEST', metrics_json='[1]')])
    report = collect(c, '2026-10-01T00:00:00Z')
    assert report['paired_structural_checks'] == {'NOT_VERIFIED_INVALID_OR_INCOMPLETE_EVIDENCE': 2}
    assert report['unique_ticker_source_structures'] == 0


def test_missing_high_is_explicit_unknown_and_no_false_completed_chain():
    c = AuditConnection([target(check())])
    report = collect(c, '2026-10-01T00:00:00Z')
    assert report['paired_structural_checks'] == {'NOT_VERIFIED_MISSING_COMPLETED_HIGH': 1}
    assert report['new_policy_completed_chains'] == 0


def test_overflow_is_reported_and_never_processed_or_looked_up():
    values = [target(check(), n) for n in range(1, 2002)]
    values[-1]['ticker'] = 'OVERFLOW'
    c = AuditConnection(values, [dict(scan_id='scan', ticker='TEST', metrics_json='{"recent_high_20d":99}')])
    report = collect(c, '2026-10-01T00:00:00Z')
    assert report['evidence_truncated']
    assert report['paired_structural_checks'] == {'BASELINE_FAIL_NEW_PASS': 2000}
    assert next(args for sql, args in c.queries if 'DISTINCT ON' in sql) == ('scan', 'TEST')
