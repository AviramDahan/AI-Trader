"""Optional cached strategy inputs, separate from baseline price acquisition.

Only the existing scanner worker calls this after an independent flag is ON.
No AI, orders, Telegram or new worker. Price downloads finish before any bounded
DB read; news publication is never substituted for a verified earnings release.
"""
from datetime import datetime, timedelta, timezone
import json
import logging

from entry_discovery import enabled_ids, instant

LOG = logging.getLogger(__name__)


def load_long_histories(symbols, cfg, *, decision_at=None):
    """Reuse existing adjusted-price cache machinery in a different cache file.

    Never overwrite the baseline six-month frame/cache or silently change its
    EMA/ATR/zone inputs. A failed long-source refresh only degrades its routes.
    """
    import pandas as pd
    import stock_scanner as scanner
    at = decision_at or datetime.now(timezone.utc)
    cache_path = scanner.ROOT / '.runtime' / 'entry-strategy-history.json.gz'
    cached, fetched = scanner._read_history_cache(cache_path=cache_path)
    expected = scanner.latest_completed_session(at)
    symbols = sorted(set(symbols))
    refresh = [symbol for symbol in symbols if symbol not in cached or
        len(cached[symbol]) < 253 or pd.Timestamp(cached[symbol].index[-1]).date() != expected or
        at.timestamp() - float(cached[symbol].attrs.get('history_fetched_at', fetched)) >= cfg['history_cache_ttl']]
    result = dict(cached)
    error = None
    if refresh:
        try:
            downloaded = scanner._download_history(refresh, period='2y')
            observed = datetime.now(timezone.utc)
            completed = {symbol: scanner._finalize_download(frame, observed.timestamp())
                         for symbol, frame in downloaded.items()}
            result.update(completed)
            scanner._write_history_cache(result, observed.timestamp(), cache_path=cache_path)
        except Exception as exc:
            error = type(exc).__name__
            LOG.warning('entry_strategy_history_degraded:%s', error)
    return {symbol: result[symbol] for symbol in symbols if symbol in result}, dict(
        status='degraded' if error else 'ready', period='2y',
        requested=len(symbols), available=sum(symbol in result for symbol in symbols),
        refresh_requested=len(refresh), error=error)


def verified_earnings_from_rows(rows, symbols, decision_at):
    """Project a typed official release fact, not an earnings headline/schedule.

    Existing collectors may store structured source_facts_json. Only explicit
    official_earnings_release / verified_earnings_release records with verified
    ticker identity AND publication timing can feed PEAD. Missing producer data
    is reported as unavailable; there is no manual watchlist or per-stock step.
    """
    at, symbols = instant(decision_at), set(symbols)
    output = {}
    for row in rows:
        try:
            symbol = row.get('ticker')
            if (symbol not in symbols or row.get('headline_only') or
                    row.get('source_kind') not in {'official_earnings_release', 'verified_earnings_release'}):
                continue
            verified = json.loads(row.get('verified_tickers_json') or '[]')
            if symbol not in verified:
                continue
            facts = json.loads(row.get('source_facts_json') or '{}')
            events = facts.get('earnings_events', []) if isinstance(facts, dict) else []
            collected, processed = instant(row['collected_at']), instant(row['analyzed_at'])
            if max(collected, processed) > at or not isinstance(events, list):
                continue
            for event in events[:20]:
                if (not isinstance(event, dict) or event.get('symbol') != symbol or
                        event.get('event_type') != 'EARNINGS_RELEASE'):
                    continue
                release = instant(event['released_at'])
                observed = max(instant(event['source_observed_at']), collected)
                completed = max(instant(event['processed_at']), processed)
                effective = max(instant(event['effective_available_at']), observed, completed, release)
                if effective > at:
                    continue
                # Preserve unverified corrections/retractions, so a newer known
                # revision cannot revive an older verified release silently.
                projected = {key: event.get(key) for key in ('event_id', 'source_id', 'event_type',
                    'symbol', 'verified', 'timing_verified', 'timing', 'released_at', 'revision', 'retracted')}
                projected.update(source_observed_at=observed.isoformat(), processed_at=completed.isoformat(),
                                 effective_available_at=effective.isoformat())
                output.setdefault(symbol, []).append(projected)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return output


def load_verified_earnings(symbols, decision_at):
    """Read immutable producer facts only, never collect or infer in a scan.

    The old typed-row parser remains a compatibility utility, not an implicit
    fallback that could resurrect a corrected/retracted producer fact.
    """
    from earnings_releases import read_facts
    try:
        return read_facts(symbols, decision_at)
    except Exception as exc:
        LOG.warning('entry_strategy_earnings_degraded:%s', type(exc).__name__)
        return {}, dict(status='unknown', reason='verified_release_store_unavailable')


def load_context(symbols, histories, universe, cfg, *, decision_at=None):
    """Build inputs automatically from existing universe/cache and typed facts."""
    import stock_scanner
    ids = enabled_ids(cfg)
    if not ids:
        return {}
    at = decision_at or datetime.now(timezone.utc)
    context = dict(expected_session=stock_scanner.latest_completed_session(at).isoformat(), by_ticker={})
    # Use the same discovery prefix regardless of which other routes are ON:
    # enabling VCP must not silently change another route's EMA seed/history.
    # The original baseline frames remain the separate six-month acquisition.
    long, coverage = load_long_histories(
        [*symbols, *(['SPY'] if 'RELATIVE_STRENGTH_LEADER' in ids else [])], cfg, decision_at=at)
    context['long_history_coverage'] = coverage
    # A newly completed download is available at the subsequent discovery
    # decision, never backdated to the scan's earlier acquisition start.
    for symbol in symbols:
        # An unavailable discovery input is UNKNOWN, not an implicit fallback
        # to a shorter/differently seeded frame. Baseline still uses histories.
        context['by_ticker'][symbol] = dict(history_frame=long.get(symbol))
    benchmark = long.get('SPY')
    if benchmark is None:
        benchmark = histories.get('SPY')
    if benchmark is not None:
        context.update(benchmark_frame=benchmark,
                       benchmark_observed_at=benchmark.attrs.get('history_fetched_at'))
    if 'PEAD' in ids:
        events, coverage = load_verified_earnings(symbols, datetime.now(timezone.utc))
        context['earnings_coverage'] = coverage
        for symbol, values in events.items():
            context['by_ticker'].setdefault(symbol, {})['earnings_events'] = values
    context['expected_session'] = stock_scanner.latest_completed_session(datetime.now(timezone.utc)).isoformat()
    return context
