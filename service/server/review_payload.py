"""Lossless removal of repeated evidence from the model view, not trade plans.

Never clips sources, zones, context or output. A field is moved only when its
existing copy is proved identical; frozen execution contracts remain untouched.
"""
import copy
import json

VERSION = 'lossless_review_evidence_v1'
INSTRUCTION = (
    'Evidence layout: recent_news contains each supplied article and its source '
    'fields once. When candidate.price_zones is absent, the identical price-zone '
    'evidence is in validated_target_plan.zones, including pivot confirmation times. '
    'This layout does not remove evidence or imply that a trade should be approved.'
)


def _identical(left, right):
    # Python equality treats True == 1 == 1.0. A source's JSON types are part
    # of the retained evidence; malformed/non-JSON inputs never prove a copy.
    try:
        return json.dumps(left, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(
            right, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False


def _zone_view(zones):
    if not isinstance(zones, list):
        return None
    projected = []
    for zone in zones:
        if not isinstance(zone, dict) or not isinstance(zone.get('pivots', []), list):
            return None
        if any(not isinstance(pivot, dict) for pivot in zone.get('pivots', [])):
            return None
        projected.append({**zone, 'pivots': [
            {key: value for key, value in pivot.items() if key != 'confirmed_at'}
            for pivot in zone.get('pivots', [])]})
    return projected


def compact(payload):
    """Return an independent payload and the exact reversible moves performed."""
    result = copy.deepcopy(payload)
    candidate = result.get('candidate')
    if not isinstance(candidate, dict):
        return result, []
    moves = []
    news = candidate.get('news')
    fields = ('title', 'publisher', 'published_at', 'relevance')
    if (isinstance(news, list) and all(isinstance(row, dict) and all(key in row for key in fields)
                                      for row in news)
            and _identical(result.get('recent_news'), [{key: row[key] for key in fields} for row in news])):
        result['recent_news'] = candidate.pop('news')
        moves.append('news')
    plan = result.get('validated_target_plan')
    zones = candidate.get('price_zones')
    if (isinstance(plan, dict) and isinstance(zones, list)
            and _identical(_zone_view(plan.get('zones')), zones)):
        candidate.pop('price_zones')
        moves.append('price_zones')
    return result, moves


def expand(payload, moves):
    """Offline equivalence witness; never used to manufacture trading inputs."""
    result = copy.deepcopy(payload)
    if 'news' in moves:
        rows = result['recent_news']
        result['candidate']['news'] = copy.deepcopy(rows)
        result['recent_news'] = [{key: row[key] for key in
                                ('title', 'publisher', 'published_at', 'relevance')} for row in rows]
    if 'price_zones' in moves:
        result['candidate']['price_zones'] = _zone_view(result['validated_target_plan']['zones'])
    return result
