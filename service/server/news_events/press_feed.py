"""Official press feeds: provider-local activation fence, no routing decisions."""
import json
import os
from datetime import datetime
from urllib.parse import urlsplit
from .model import timestamp
from .providers import RSSProvider, ProviderFailure, Transport


class PressFeedProvider(RSSProvider):
    def __init__(self, config, transport=None):
        super().__init__(config, transport or Transport([urlsplit(config.endpoint).hostname],
            user_agent='AI-Trader/1.0 (+https://github.com/AviramDahan/AI-Trader)'))

    def fetch(self, state, now):
        boundary = os.getenv('NEWS_' + self.provider_id.upper() + '_ACTIVATED_AT', '')
        if not boundary:
            raise ProviderFailure('press_feed_activation_required', terminal=True)
        boundary = datetime.fromisoformat(timestamp(boundary))
        try:
            response = super().fetch(state, now)
        except ProviderFailure as exc:
            # A previously verified feed's intermittent 404 gets two delayed
            # probes, not permanent suspension after one response or a tight loop.
            if exc.http_status == 404 and state.get('last_success') and state.get('attempts', 0) < 2:
                raise ProviderFailure('verified_feed_http_404', 404, max(300, exc.retry_after), False) from None
            raise
        accepted = []
        blocked = 0
        for raw in response['items']:
            # Explicit offset is required by the shared timestamp validator.
            if datetime.fromisoformat(self.source_timestamp(raw)) < boundary:
                blocked += 1
            else:
                accepted.append(raw)
        checkpoint = json.loads(state.get('checkpoint_json') or '{}')
        checkpoint.update(activation_boundary=timestamp(boundary), replay_blocked=blocked)
        return {**response, 'items': accepted, 'raw_item_count': len(response['items']),
                'checkpoint': checkpoint}
