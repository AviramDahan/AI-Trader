"""Opt-in price-route news context; never an order/fill/exit policy.

No providers, AI, database or mutation. Baseline-only, PEAD and SHORT retain the
existing mandatory-evidence policy. A mixed detection needs a still-valid price
route, not merely its Baseline branch, to use the exception.
"""
import os

VERSION = 'price_route_news_context_v1'
FLAG = 'STOCK_SCANNER_PRICE_NEWS_CONTEXT_ENABLED'
BLOCK_REASONS = frozenset({'price_news_policy_invalid_routes', 'price_news_policy_invalid_context',
    'price_news_policy_evidence_mismatch', 'price_news_policy_no_valid_price_trigger',
    'price_news_policy_invented_news_scores', 'news_evidence_unavailable_fail_closed',
    'price_news_policy_retained_attribution_mismatch'})
ROUTES = frozenset({'VCP_BASE_CONTRACTION', 'STOCKBEE_MOMENTUM_BURST',
                    'TREND_PULLBACK_RECLAIM', 'RELATIVE_STRENGTH_LEADER'})


def public_context(context):
    keys = {'version', 'mode', 'strategy_ids', 'observed_strategy_ids', 'availability', 'yahoo_lookup',
            'canonical_lookup', 'numeric_news_scores'}
    if (not isinstance(context, dict) or set(context) != keys or context.get('version') != VERSION or
            context.get('mode') != 'price_context' or
            not isinstance(context.get('strategy_ids'), list) or not context['strategy_ids'] or
            len(context['strategy_ids']) != len(set(context['strategy_ids'])) or
            not set(context['strategy_ids']) <= ROUTES or
            not isinstance(context.get('observed_strategy_ids'), list) or
            not set(context['strategy_ids']) <= set(context['observed_strategy_ids']) or
            len(context['observed_strategy_ids']) != len(set(context['observed_strategy_ids'])) or
            not set(context['observed_strategy_ids']) <= ROUTES | {'BASELINE', 'PEAD'} or
            context.get('availability') not in {'AVAILABLE', 'NO_ELIGIBLE_STORIES'} or
            context.get('yahoo_lookup') not in {'OK', 'UNAVAILABLE'} or
            context.get('canonical_lookup') not in {'OK', 'UNAVAILABLE'} or
            context.get('numeric_news_scores') != ('MODEL_ASSESSMENT' if context.get('availability') == 'AVAILABLE'
                                                  else 'NOT_MEASURED_ZERO_WIRE_PLACEHOLDERS')):
        raise ValueError('price_news_policy_invalid_context')
    return {k:list(v) if isinstance(v, list) else v for k,v in context.items()}


def enabled():
    return os.getenv(FLAG, 'false').lower() == 'true'


def route_ids(candidate, cfg):
    if cfg.get('price_news_context_enabled') is not True or candidate.get('technical_direction') != 'BUY':
        return []
    from entry_discovery import validate_attribution, enabled_ids
    package = candidate.get('entry_discovery')
    if package is None:
        return []
    package = validate_attribution(package)
    allowed = set(enabled_ids(cfg)) & ROUTES
    return [key for key in package['strategy_ids'] if key in allowed]


def attach(candidate, ids, news, *, yahoo_ok, canonical_ok):
    if not ids or not set(ids) <= ROUTES:
        raise ValueError('price_news_policy_invalid_routes')
    # A successful empty lookup is not equivalent to unavailable coverage.
    # Existing eligible evidence may still substitute for a failed provider.
    if not news and not (yahoo_ok and canonical_ok):
        raise ValueError('news_evidence_unavailable_fail_closed')
    return dict(version=VERSION, mode='price_context', strategy_ids=list(ids),
        observed_strategy_ids=list(candidate['entry_discovery']['strategy_ids']),
        availability='AVAILABLE' if news else 'NO_ELIGIBLE_STORIES',
        yahoo_lookup='OK' if yahoo_ok else 'UNAVAILABLE',
        canonical_lookup='OK' if canonical_ok else 'UNAVAILABLE',
        numeric_news_scores='MODEL_ASSESSMENT' if news else 'NOT_MEASURED_ZERO_WIRE_PLACEHOLDERS')


def validate(candidate, cfg, price, quote_at, decision_at):
    """Both pre-AI and post-AI quotes must support an opted-in price branch."""
    context = candidate.get('news_context')
    if context is None:
        return False
    context = public_context(context)
    ids = route_ids(candidate, cfg)
    if (not ids or not isinstance(context, dict) or context.get('version') != VERSION or
            context.get('mode') != 'price_context' or context.get('strategy_ids') != ids or
            context.get('availability') not in {'AVAILABLE', 'NO_ELIGIBLE_STORIES'}):
        raise ValueError('price_news_policy_invalid_context')
    empty = not candidate.get('news')
    if empty != (context['availability'] == 'NO_ELIGIBLE_STORIES'):
        raise ValueError('price_news_policy_evidence_mismatch')
    if empty and (context.get('yahoo_lookup') != 'OK' or context.get('canonical_lookup') != 'OK'):
        raise ValueError('news_evidence_unavailable_fail_closed')
    from entry_strategies import validate_trigger
    for record in candidate['entry_discovery']['detections']:
        if record['strategy_id'] in ids:
            try:
                validate_trigger(record, price, quote_at, decision_at)
                return True
            except ValueError:
                pass
    raise ValueError('price_news_policy_no_valid_price_trigger')


def prepare_admission(candidate, cfg, price, quote_at, decision_at):
    """Use unchanged v1 price execution contracts, retaining every detection.

    A Baseline overlap must not enable a later Baseline-only fill after the
    independent branch ceases to satisfy its frozen price rules. The original
    full package stays in the signal's technical JSON and the discovery journal;
    the execution package contains ONLY the eligible enabled price branches.
    No retained contract is rewritten and no new snapshot format is introduced.
    """
    if not validate(candidate, cfg, price, quote_at, decision_at):
        return candidate
    from entry_discovery import validate_attribution, attribution
    package = validate_attribution(candidate['entry_discovery'])
    ids = candidate['news_context']['strategy_ids']
    records = [r for r in package['detections'] if r['strategy_id'] in ids]
    executable = attribution(records, package['detected_at'])
    return dict(candidate, observed_entry_discovery=package, entry_discovery=executable,
                strategy_ids=executable['strategy_ids'], strategy_id=executable['primary_strategy_id'])


def retained_metadata(technical):
    """Validate the frozen audit association without consulting creation flags."""
    if not any(k in technical for k in ('news_context', 'observed_entry_discovery')):
        return {}
    from entry_discovery import validate_attribution, attribution
    ctx = public_context(technical.get('news_context'))
    observed = validate_attribution(technical.get('observed_entry_discovery'))
    executable = validate_attribution(technical.get('entry_discovery'))
    records = [r for r in observed['detections'] if r['strategy_id'] in ctx['strategy_ids']]
    if (ctx['observed_strategy_ids'] != observed['strategy_ids'] or
            executable != attribution(records, observed['detected_at'])):
        raise ValueError('price_news_policy_retained_attribution_mismatch')
    return dict(news_context=ctx, observed_entry_discovery=observed)


def decision_failures(decision, cfg, *, sec_current=False, price_context=False,
                      material_conflict=False):
    """Same vetoes; only the relevant-news requirement is conditional."""
    failures = []
    if decision['action'] == 'HOLD':
        failures.append('ai_hold')
    if decision['confidence'] < cfg['min_confidence']:
        failures.append('ai_confidence_below_threshold')
    if sec_current and decision['action'] == 'BUY' and material_conflict:
        failures.append('sec_material_conflict_hold')
    if decision['news_relevance'] < .6 and not sec_current and not price_context:
        failures.append('ai_news_relevance_below_threshold')
    return failures
