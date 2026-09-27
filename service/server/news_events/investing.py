"""Investing US RSS only: explicit operational UTC assumption, never inferred TZ."""
import json
import logging
import os
from collections import Counter
from datetime import datetime,timezone,timedelta
from urllib.parse import urlsplit
from .model import timestamp
from .providers import RSSProvider,ProviderFailure


class InvestingProvider(RSSProvider):
    def __init__(self,config,transport=None,*,activation=None,max_age_hours=None):
        super().__init__(config,transport)
        self.activation=activation or os.getenv('NEWS_INVESTING_ACTIVATED_AT','')
        self.max_age_hours=max_age_hours if max_age_hours is not None else max(24,min(720,int(os.getenv('STOCK_SCANNER_NEWS_FEED_MAX_AGE_HOURS','168'))))

    def _time(self,raw):
        endpoint=urlsplit(self.config.endpoint)
        if endpoint.scheme!='https' or endpoint.hostname!='www.investing.com' or not endpoint.path.startswith('/rss/'):
            raise ValueError('investing_rule_endpoint_mismatch')
        value=str(raw['published_at'])
        try:dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:dt=datetime.fromisoformat(timestamp(value))
        naive=dt.tzinfo is None
        if naive:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc),naive

    def source_timestamp(self,raw):
        return self._time(raw)[0].isoformat().replace('+00:00','Z')

    def raw_metadata(self,raw):
        _,naive=self._time(raw)
        return {**super().raw_metadata(raw),'timestamp_source':'investing_rss',
                'source_timezone':'UTC' if naive else 'explicit_source_offset',
                'timezone_resolution':'provider_specific_operational_rule' if naive else 'explicit_source_timestamp',
                'original_timestamp':raw['published_at'],'activation_boundary':self.activation}

    def normalize(self,raw,collected_at):
        published,_=self._time(raw)
        now=datetime.fromisoformat(timestamp(collected_at))
        if published>now+timedelta(minutes=10):raise ValueError('investing_future_timestamp')
        if published<now-timedelta(hours=self.max_age_hours):raise ValueError('investing_stale_timestamp')
        if not self.activation:raise ValueError('investing_activation_required')
        if published<datetime.fromisoformat(timestamp(self.activation)):raise ValueError('investing_pre_activation')
        return super().normalize(raw,collected_at)

    def fetch(self,state,now):
        if not self.activation:raise ProviderFailure('investing_activation_required',terminal=True)
        # Validate the boundary before any network access. No local TZ fallback.
        timestamp(self.activation)
        response=super().fetch(state,now);accepted=[];rejected=Counter()
        for raw in response['items']:
            try:self.normalize(raw,now)
            except (ValueError,TypeError,KeyError) as exc:
                reason=str(exc) if str(exc) in {'investing_future_timestamp','investing_stale_timestamp','investing_pre_activation'} else 'investing_invalid_timestamp'
                rejected[reason]+=1
                continue
            accepted.append(raw)
        prior=json.loads(state.get('checkpoint_json') or '{}')
        anomaly=rejected['investing_future_timestamp']+rejected['investing_invalid_timestamp']
        strikes=prior.get('timestamp_anomaly_polls',0)+1 if anomaly else 0
        checkpoint={'timestamp_anomaly_polls':strikes,'rejected':dict(rejected),
                    'activation_boundary':self.activation,'timezone_mode':'UTC operational rule'}
        if anomaly:
            logging.getLogger(__name__).warning('Investing RSS timestamp guard rejected=%s',dict(rejected))
        if strikes>=2:
            raise ProviderFailure('investing_repeated_timestamp_anomaly',terminal=True)
        return {**response,'items':accepted,'raw_item_count':len(response['items']),
                'checkpoint':checkpoint,'status':'degraded' if anomaly else 'ok',
                'errors':['investing_timestamp_anomaly'] if anomaly else []}
