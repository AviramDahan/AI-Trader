"""Invented causal discovery controls, never market history or trade evidence.

Reuse the strategy owner's positive fixtures, then deliberately construct
legacy-baseline misses while preserving the unchanged shared liquidity/ATR
requirements. Large old spikes/declines here are invented test controls, not
backtest data, outlier cleaning or parameter optimization on a market sample.
"""
from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / 'service' / 'server'


def fixture_module():
    if str(SERVER) not in sys.path:
        sys.path.insert(0, str(SERVER))
    path = SERVER / 'tests' / 'test_entry_strategies.py'
    spec = importlib.util.spec_from_file_location('entry_strategy_positive_controls', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encode_bars(frame):
    return [{'date': index.date().isoformat(), **{name: float(row[name]) for name in
             ('Open', 'High', 'Low', 'Close', 'Volume')}} for index, row in frame.iterrows()]


def encode_context(context):
    encoded = {}
    for key, value in context.items():
        if key in {'benchmark_frame', 'sector_frame'}:
            encoded[key.replace('_frame', '_bars')] = encode_bars(value)
        elif hasattr(value, 'isoformat'):
            encoded[key] = value.isoformat()
        else:
            encoded[key] = value
    return encoded


def common_eligible(frame):
    """Make test liquidity/ATR sufficient without changing any trading gate."""
    frame = frame.copy(deep=True)
    frame['Volume'] *= 3
    for position in range(len(frame)-65, len(frame)-1):
        row = frame.iloc[position]
        frame.iloc[position, frame.columns.get_loc('High')] = max(row['High'], row['Close']+.65, row['Open'])
        frame.iloc[position, frame.columns.get_loc('Low')] = min(row['Low'], row['Close']-.65, row['Open'])
    return frame


def constant_candles(frame, start, stop, value):
    frame.iloc[start:stop, frame.columns.get_indexer(['Open', 'High', 'Low', 'Close'])] = [value-.05, value+.65, value-.65, value]


def positive_baseline_miss(strategy_id):
    import numpy as np
    frame, context, decision, observed = fixture_module().fixture_case(strategy_id)
    frame = common_eligible(frame)
    if strategy_id == 'STOCKBEE_MOMENTUM_BURST':
        # A prior downtrend is outside this independent burst's recent base.
        constant_candles(frame, 0, len(frame)-21, 200)
    elif strategy_id == 'PEAD':
        # Previously elevated prices impair old technical checks; the invented
        # verified earnings event still creates a later, independent gap/base.
        constant_candles(frame, 0, len(frame)-40, 80)
        constant_candles(frame, len(frame)-40, len(frame)-6, 130)
        constant_candles(frame, len(frame)-6, len(frame)-5, 100)
    elif strategy_id == 'TREND_PULLBACK_RECLAIM':
        closes = np.r_[np.linspace(70, 90, 213), np.full(30, 113.), np.full(9, 101.), 107.]
        frame.iloc[:, frame.columns.get_indexer(['Open', 'High', 'Low', 'Close'])] = np.c_[closes-.05, closes+.65, closes-.65, closes]
        frame.iloc[-1, frame.columns.get_indexer(['Open', 'High', 'Low', 'Close'])] = [105, 107.2, 104.8, 107]
    elif strategy_id == 'RELATIVE_STRENGTH_LEADER':
        # An old spike lies outside the20-session trigger base but affects the
        # old EMA/RSI checks. This is intentionally invented, not market evidence.
        constant_candles(frame, len(frame)-21, len(frame)-1, 100)
        constant_candles(frame, len(frame)-22, len(frame)-21, 280)
    frame.attrs['history_fetched_at'] = observed.timestamp()
    return frame, context, decision, observed


def build_dataset():
    import numpy as np
    ids = ('VCP_BASE_CONTRACTION', 'STOCKBEE_MOMENTUM_BURST', 'PEAD',
           'TREND_PULLBACK_RECLAIM', 'RELATIVE_STRENGTH_LEADER')
    symbols = ('VCPC', 'BURST', 'PEADC', 'PULL', 'RSL')
    observations = []
    for strategy_id, ticker in zip(ids, symbols):
        frame, context, decision, observed = positive_baseline_miss(strategy_id)
        if strategy_id == 'PEAD':
            context['symbol'] = ticker
            for event in context['earnings_events']:
                event['symbol'] = ticker
        observations.append({'ticker': ticker, 'company': 'Invented discovery control',
            'source_observed_at': observed.isoformat(), 'bars': encode_bars(frame),
            'context': encode_context(context), 'intended_strategy': strategy_id,
            'mock_outcome': {'ai_reviewed': True, 'ai_approved': True,
                             'signal': True, 'order': True, 'entry': False}})
    frame, _, decision, observed = fixture_module().fixture_case('VCP_BASE_CONTRACTION')
    closes = np.linspace(70, 100, len(frame))
    frame.iloc[:, :4] = np.c_[closes-.05, closes+.65, closes-.65, closes]
    frame['Volume'] = 3_000_000
    frame.attrs['history_fetched_at'] = observed.timestamp()
    observations.append({'ticker': 'BASE', 'company': 'Invented baseline control',
        'source_observed_at': observed.isoformat(), 'bars': encode_bars(frame),
        'context': {'expected_session': '2026-10-05'}, 'intended_strategy': 'BASELINE'})
    return {'version': 1, 'synthetic': True, 'kind': 'SYNTHETIC_CAUSAL_CONTROLS_NOT_MARKET_HISTORY',
            'fixture_source_sha256': {path.relative_to(REPO).as_posix(): hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                for path in (Path(__file__), SERVER / 'tests' / 'test_entry_strategies.py')},
            'fixture_code_hash_newline_policy': 'LF',
            'snapshots': [{'snapshot_id': 'invented_six_path_controls',
                           'decision_at': decision.isoformat(), 'observations': observations}],
            'limitations': ['All prices, benchmark and earnings facts are invented controls.',
                            'Mock AI/signals/orders are declared inputs only; no actual AI or lifecycle was executed.',
                            'entry=False explicitly prevents equating a mock pending order with a position.']}
