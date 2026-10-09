"""Official press feeds: provider-local activation fence, no routing decisions."""
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from .model import timestamp
from .providers import RSSProvider, ProviderFailure, Transport


class PressFeedProvider(RSSProvider):
    def __init__(self, config, transport=None):
        super().__init__(config, transport or Transport([urlsplit(config.endpoint).hostname],
            user_agent='AI-Trader/1.0 (+https://github.com/AviramDahan/AI-Trader)',read_timeout=10,
            prefer_ipv4=config.provider_id=='globenewswire'))

    def recover_terminal(self, state, now):
        """One delayed probe per verified 403 incident; never unblock new feeds.

        Persisted before I/O by the collector. A failed probe stays terminal;
        rights, metadata, unsafe-endpoint failures and first-use denials are
        never recoverable here. Recovery fences out the outage backlog.
        """
        success = state.get('last_success')
        if (not self.config.enabled or self.config.rights != 'approved' or
                not state.get('terminal') or state.get('http_status') != 403 or
                state.get('error') != 'http_error' or not success):
            return None
        checkpoint = json.loads(state.get('checkpoint_json') or '{}')
        if checkpoint.get('access_recovery_for') == success:
            return None
        try:
            attempted = datetime.fromisoformat(timestamp(state['last_attempt']))
            if now < attempted + timedelta(hours=1):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        checkpoint.update(access_recovery_for=success, recovery_not_before=timestamp(now))
        return {**state, 'terminal': False, 'attempts': 0,
                'checkpoint_json': json.dumps(checkpoint)}

    def fetch(self, state, now):
        boundary = os.getenv('NEWS_' + self.provider_id.upper() + '_ACTIVATED_AT', '')
        if not boundary:
            raise ProviderFailure('press_feed_activation_required', terminal=True)
        boundary = datetime.fromisoformat(timestamp(boundary))
        checkpoint = json.loads(state.get('checkpoint_json') or '{}')
        # An operator-verified recovery must not replay the outage backlog.
        if checkpoint.get('recovery_not_before'):
            boundary = max(boundary, datetime.fromisoformat(timestamp(checkpoint['recovery_not_before'])))
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
        checkpoint.update(activation_boundary=timestamp(boundary), replay_blocked=blocked)
        return {**response, 'items': accepted, 'raw_item_count': len(response['items']),
                'checkpoint': checkpoint}
