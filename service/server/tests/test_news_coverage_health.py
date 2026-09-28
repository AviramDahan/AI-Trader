from news_events.watch import coverage_summary


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
