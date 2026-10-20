from unittest.mock import Mock
import pytest
import stock_scanner as scanner
from review_evidence import ObservedQuote


def quote():
    return ObservedQuote(101.,'2026-10-20T14:00:00Z',{},volume_frame=object(),
        source_observed_at='2026-10-20T14:00:01Z',completed_before='2026-10-20T14:00:00Z',
        volume_source={'explicit':True})


def test_disabled_context_has_no_cache_or_provider_io(monkeypatch):
    import intraday_volume
    producer=Mock(side_effect=AssertionError('OFF performed IO'))
    monkeypatch.setattr(intraday_volume,'get_evidence',producer)
    for enabled in (False,None,'false',1):
        q=quote();assert scanner._ScanVolumeEvidence(enabled=enabled).attach('TEST',q) is q
    producer.assert_not_called()


def test_six_distinct_acquisitions_shared_between_all_candidates_and_rechecks(monkeypatch):
    import intraday_volume
    calls=[];cached=set()
    def producer(ticker, frame, *, acquire, **kwargs):
        calls.append((ticker,acquire))
        if acquire:cached.add(ticker)
        return intraday_volume.unknown('UNKNOWN_NOT_ENOUGH_HISTORY' if ticker in cached else 'UNKNOWN_HISTORY_CACHE_MISS')
    monkeypatch.setattr(intraday_volume,'get_evidence',producer)
    budget=scanner._ScanVolumeEvidence(enabled=True,fetcher=Mock())
    for ticker in ['AAA','BBB','CCC','DDD','EEE','FFF','GGG','AAA','GGG']:
        budget.attach(ticker,quote())
    acquired=[ticker for ticker,acquire in calls if acquire]
    assert acquired==['AAA','BBB','CCC','DDD','EEE','FFF']
    assert len(budget.acquired)==6


def test_collector_failure_is_unknown_not_a_baseline_or_ai_gate(monkeypatch):
    import intraday_volume
    monkeypatch.setattr(intraday_volume,'get_evidence',Mock(side_effect=ValueError('bad cache')))
    q=scanner._ScanVolumeEvidence(enabled=True).attach('TEST',quote())
    assert q[0]==101 and q.evidence['relative_volume']['status']=='UNKNOWN'
    assert q.evidence['same_time_of_day_relative_volume'] is None
