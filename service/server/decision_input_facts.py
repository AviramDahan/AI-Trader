"""Private, bounded facts from the actual initial AI user payload, not replay.

No prompts, model output, article body, identities, portfolio or arbitrary nested
objects are retained. Exact input hashes and sanitized-projection hashes have
different names/scopes. A hash is not a substitute for missing source content.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone

VERSION = 'decision_input_facts_v1'
MAX_BYTES = 24576
NUMBERS = frozenset({'price', 'daily_reference_close', 'volume_ratio', 'rsi14',
    'ema20', 'ema50', 'macd_histogram', 'atr', 'atr_pct', 'return_20d_pct',
    'recent_high_20d', 'recent_low_20d', 'average_dollar_volume',
    'realized_volatility_pct', 'news_relevance', 'news_sentiment', 'score'})
TEXT = frozenset({'ticker', 'daily_reference_as_of', 'entry_quote_as_of',
    'history_fetched_at', 'history_as_of'})
OMISSIONS = ['system_prompt', 'article_bodies', 'unprojected_candidate_fields',
    'unprojected_source_fields', 'provider_wire_body', 'historical_source_revisions']


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value, limit):
    from decision_explanation import public_reason
    safe = public_reason(value)
    return safe[:limit] if safe is not None else None


def _scalars(value, numbers=(), text=(), boolean=()):
    if not isinstance(value, dict):
        return {}
    out = {key: value[key] for key in numbers if key in value and _finite(value[key])}
    out.update({key: _text(value[key], 96) for key in text if _text(value.get(key), 96) is not None})
    out.update({key: value[key] for key in boolean if type(value.get(key)) is bool})
    return out


def capture(payload, user_content, *, observed_at=None):
    if not isinstance(payload, dict) or not isinstance(user_content, str):
        raise ValueError('invalid_input_facts')
    # Prove these are the actual facts sent, not a separately reconstructed plan.
    if len(user_content.encode('utf-8')) > 262144 or digest(json.loads(user_content)) != digest(payload):
        raise ValueError('input_facts_payload_mismatch')
    at = observed_at or datetime.now(timezone.utc).isoformat()
    stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('input_facts_timezone_required')
    candidate = _scalars(payload.get('candidate'), NUMBERS, TEXT)
    market = {}
    raw_market = payload.get('market_context')
    if isinstance(raw_market, dict):
        for name in ('SPY', 'QQQ'):
            if name in raw_market:
                market[name] = _scalars(raw_market[name], ('close', 'return_20d_pct'),
                    ('as_of', 'source_observed_at'), ('above_ema20', 'ema20_above_ema50'))
    news = []
    raw_news = payload.get('recent_news')
    if isinstance(raw_news, list):
        for item in raw_news[:10]:
            if not isinstance(item, dict):
                continue
            fields = {key: _text(item.get(key), limit) for key, limit in
                (('title', 256), ('publisher', 80), ('published_at', 64))}
            fields['relevance'] = item.get('relevance') if _finite(item.get('relevance')) else None
            fields.update(actual_item_sha256=digest(item),
                title_truncated=isinstance(item.get('title'), str) and len(item['title']) > 256,
                text_omitted_for_privacy=any(isinstance(item.get(key),str) and fields[key] is None
                    for key in ('title','publisher','published_at')),
                article_body_retained=False, source_identity_status='NOT_IN_MODEL_NEWS_PROJECTION')
            news.append(fields)
    context = payload.get('review_evidence_context')
    context = context if isinstance(context, dict) else {}
    quote = _scalars(context.get('entry_quote'), ('price', 'age_seconds'), ('as_of', 'source'), ('fresh',))
    intraday = context.get('intraday')
    if not isinstance(intraday, dict):
        intraday = context.get('intraday_completed_5m')
    intraday = intraday if isinstance(intraday, dict) else {}
    bars = []
    if isinstance(intraday.get('bars'), list):
        for bar in intraday['bars'][:6]:
            bars.append(_scalars(bar, ('open', 'high', 'low', 'close', 'volume'),
                ('start_at', 'end_at', 'available_at'), ('close_above_completed_20d_high',)))
    volume = intraday.get('relative_volume')
    volume = volume if isinstance(volume, dict) else {}
    clocks = _scalars(volume.get('source_times'), (),
        ('decision_at', 'current_observed_at', 'history_observed_at', 'completed_before'))
    volume = _scalars(volume, ('same_time_of_day_relative_volume', 'prior_session_count',
        'current_cumulative_volume', 'prior_cumulative_mean'),
        ('version', 'status', 'reason', 'completed_through', 'sourcehash', 'calendar_id', 'calendar_version'))
    if clocks:
        volume['source_times'] = clocks
    projected = dict(candidate=candidate, market_context=market, recent_news=news,
        news_count=len(raw_news) if isinstance(raw_news, list) else None,
        quote=quote, completed_intraday=bars, relative_volume=volume,
        context_version=_text(context.get('version'), 64))
    daily = context.get('completed_daily')
    if isinstance(daily, dict):
        projected['completed_daily'] = _scalars(daily, ('reference_close',),
            ('as_of', 'expected_session', 'coverage'), ('current_session_volume_available',))
        projected['completed_daily']['metrics'] = _scalars(daily.get('metrics'), NUMBERS)
    projected['entry_price_facts'] = _scalars(context.get('entry_price_facts'),
        ('quote_price', 'planned_entry', 'difference'),
        ('version', 'status', 'relation', 'quote_at', 'basis'))
    projected['target_policy'] = _scalars(context.get('target_policy'),
        ('completed_high', 'completed_high_sessions', 'minimum_rr'),
        ('policy_version', 'target_kind', 'source_data_at'))
    result = dict(version=VERSION, status='RECORDED_PARTIAL_ALLOWLIST', observed_at=at,
        initial_user_content_utf8_sha256=hashlib.sha256(user_content.encode('utf-8')).hexdigest(),
        initial_user_content_bytes=len(user_content.encode('utf-8')),
        sanitized_projection_sha256=digest(projected), facts=projected,
        source_content_reconstructible=False,
        omissions=OMISSIONS)
    if len(_wire(result)) > MAX_BYTES:
        raise ValueError('input_facts_exceeds_bound')
    return validate(json.loads(_wire(result)))


def validate(value):
    """Validate stored projection independently of its claimed version/hash."""
    top = {'version','status','observed_at','initial_user_content_utf8_sha256',
        'initial_user_content_bytes','sanitized_projection_sha256','facts',
        'source_content_reconstructible','omissions'}
    sha = lambda v: isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) is not None
    if (not isinstance(value,dict) or set(value)!=top or value['version']!=VERSION or
            value['status']!='RECORDED_PARTIAL_ALLOWLIST' or
            value['source_content_reconstructible'] is not False or value['omissions']!=OMISSIONS or
            type(value['initial_user_content_bytes']) is not int or
            not 0<value['initial_user_content_bytes']<=262144 or
            not sha(value['initial_user_content_utf8_sha256']) or
            not sha(value['sanitized_projection_sha256'])):
        raise ValueError('invalid_input_facts_schema')
    stamp=datetime.fromisoformat(value['observed_at'].replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('input_facts_timezone_required')
    f=value['facts']
    allowed={'candidate','market_context','recent_news','news_count','quote',
        'completed_intraday','relative_volume','context_version','completed_daily',
        'entry_price_facts','target_policy'}
    if not isinstance(f,dict) or set(f)-allowed or not sha(digest(f)) or digest(f)!=value['sanitized_projection_sha256']:
        raise ValueError('invalid_input_facts_projection')
    def scalars(v,n=(),s=(),b=()):
        if not isinstance(v,dict) or set(v)-(set(n)|set(s)|set(b)):
            raise ValueError('invalid_input_facts_fields')
        if (any(not _finite(v[k]) for k in v if k in n) or
                any(not isinstance(v[k],str) or len(v[k])>96 or _text(v[k],96)!=v[k] for k in v if k in s) or
                any(type(v[k]) is not bool for k in v if k in b)):
            raise ValueError('invalid_input_facts_types')
    scalars(f.get('candidate',{}),NUMBERS,TEXT)
    market=f.get('market_context',{})
    if not isinstance(market,dict) or set(market)-{'SPY','QQQ'}:raise ValueError('invalid_input_facts_market')
    for m in market.values():scalars(m,('close','return_20d_pct'),('as_of','source_observed_at'),('above_ema20','ema20_above_ema50'))
    scalars(f.get('quote',{}),('price','age_seconds'),('as_of','source'),('fresh',))
    bars=f.get('completed_intraday',[])
    if not isinstance(bars,list) or len(bars)>6:raise ValueError('invalid_input_facts_bars')
    for bar in bars:scalars(bar,('open','high','low','close','volume'),('start_at','end_at','available_at'),('close_above_completed_20d_high',))
    volume=dict(f.get('relative_volume',{}));clocks=volume.pop('source_times',{})
    scalars(clocks,(),('decision_at','current_observed_at','history_observed_at','completed_before'))
    scalars(volume,('same_time_of_day_relative_volume','prior_session_count','current_cumulative_volume','prior_cumulative_mean'),
        ('version','status','reason','completed_through','sourcehash','calendar_id','calendar_version'))
    daily=dict(f.get('completed_daily',{}));metrics=daily.pop('metrics',{})
    scalars(daily,('reference_close',),('as_of','expected_session','coverage'),('current_session_volume_available',))
    scalars(metrics,NUMBERS)
    scalars(f.get('entry_price_facts',{}),('quote_price','planned_entry','difference'),('version','status','relation','quote_at','basis'))
    scalars(f.get('target_policy',{}),('completed_high','completed_high_sessions','minimum_rr'),('policy_version','target_kind','source_data_at'))
    if f.get('context_version') is not None and (not isinstance(f['context_version'],str) or len(f['context_version'])>64 or _text(f['context_version'],64)!=f['context_version']):raise ValueError('invalid_input_facts_context')
    count=f.get('news_count')
    if count is not None and (type(count) is not int or not 0<=count<=10000):raise ValueError('invalid_input_facts_news_count')
    news=f.get('recent_news',[])
    if not isinstance(news,list) or len(news)>10:raise ValueError('invalid_input_facts_news')
    fields={'title','publisher','published_at','relevance','actual_item_sha256','title_truncated',
        'text_omitted_for_privacy','article_body_retained','source_identity_status'}
    for item in news:
        if (not isinstance(item,dict) or set(item)!=fields or not sha(item['actual_item_sha256']) or
                type(item['title_truncated']) is not bool or type(item['text_omitted_for_privacy']) is not bool or
                item['article_body_retained'] is not False or item['source_identity_status']!='NOT_IN_MODEL_NEWS_PROJECTION' or
                (item['relevance'] is not None and not _finite(item['relevance']))):raise ValueError('invalid_input_facts_news_item')
        for key,limit in (('title',256),('publisher',80),('published_at',64)):
            if item[key] is not None and (not isinstance(item[key],str) or len(item[key])>limit or _text(item[key],limit)!=item[key]):raise ValueError('invalid_input_facts_news_text')
    if len(_wire(value))>MAX_BYTES:raise ValueError('input_facts_exceeds_bound')
    return json.loads(_wire(value))
