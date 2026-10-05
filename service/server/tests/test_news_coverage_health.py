from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from news_events.watch import coverage_summary, summary_key


def test_routine_report_has_six_four_hour_buckets_per_day():
    at = datetime(2026, 10, 5, tzinfo=timezone.utc)
    keys = [summary_key(at+timedelta(minutes=i)) for i in range(24*60)]
    assert len(set(keys)) == 6
    assert keys[0] == keys[239] == 'canonical_health:2026-10-05T00'
    assert keys[240] == 'canonical_health:2026-10-05T04'
    assert keys[-1] == 'canonical_health:2026-10-05T20'
    assert summary_key(at+timedelta(days=1)) != keys[-1]


def test_summary_key_is_restart_and_timezone_independent():
    for at in (datetime(2026, 10, 5, 5, tzinfo=timezone.utc),
               datetime(2026, 10, 25, 0, tzinfo=timezone.utc)):
        assert summary_key(at) == summary_key(at.astimezone(ZoneInfo('Asia/Jerusalem')))
        assert summary_key(at) == summary_key(datetime.fromisoformat(at.isoformat()))


def test_terminal_provider_is_visible_without_declaring_pipeline_broken():
    message = coverage_summary([{'provider': 'yahoo', 'status': 'ok'}],
                               {'prnewswire': {'status': 'requires_configuration'}})
    assert 'כיסוי מקורות חלקי' in message
    assert 'prnewswire' in message
    assert 'הצינור תקין' in message


def test_disabled_and_retired_are_not_outages():
    message = coverage_summary([{'provider': 'intel_ir', 'status': 'retired'}],
                               {'benzinga': {'status': 'disabled'}, 'investing': {'status': 'ok'}})
    assert 'המקורות הפעילים תקינים' in message


def test_recovery_clears_partial_coverage_and_legacy_failure_is_visible():
    assert 'כיסוי מקורות חלקי' not in coverage_summary([], {'prnewswire': {'status': 'ok'}})
    assert 'yahoo' in coverage_summary([{'provider': 'yahoo', 'status': 'error'}], {})
