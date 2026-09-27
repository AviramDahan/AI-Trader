"""Provider enablement requires an explicit, retained license approval reference.

Default blocked states are based on the 2026-09-27 access/terms review. Secrets
come from server environment only. An RSS URL alone never constitutes a license.
"""
import json
import os
from dataclasses import replace
from .providers import DEFAULT_CONFIGS, registry

BLOCKERS={
 'investing':'UTC operational rule requires explicit activation boundary and enablement',
 'globenewswire':'cloud_http_response_timeout_after_successful_dns_tls; feed_license_confirmation_required',
 'prnewswire':'not_enabled',
 'benzinga':'free_news_api_credential_missing; official_rss_unavailable',
 'tipranks':'enterprise_market_news_contract_endpoint_schema_and_credentials_required',
}


def configured():
    approvals=json.loads(os.getenv('NEWS_EVENTS_PROVIDER_APPROVALS','{}'))
    enabled=set(filter(None,os.getenv('NEWS_EVENTS_PROVIDERS','').split(',')))
    configs=[]
    for original in DEFAULT_CONFIGS:
        pid=original.provider_id
        # A license cannot resolve missing source timestamps/contracts.
        supported=pid!='tipranks' and (pid!='investing' or bool(os.getenv('NEWS_INVESTING_ACTIVATED_AT')))
        live=pid in enabled and bool(approvals.get(pid)) and supported
        configs.append(replace(original,enabled=live,rights='approved' if live else 'review_required',
            credential=os.getenv('NEWS_'+pid.upper()+'_API_KEY','')))
    return configs


def collect(p,at):
    from .model import timestamp
    configs=configured()
    with p.store.transaction(True) as c:
        before={r['provider_id']:json.loads(r['state_json']) for r in c.execute('SELECT * FROM ne_provider_state')}
        for cfg in configs:
            if cfg.enabled:continue
            value={'status':'disabled','error':BLOCKERS[cfg.provider_id],'next_at':None}
            c.execute('INSERT INTO ne_provider_state VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET state_json=excluded.state_json',
                (cfg.provider_id,json.dumps(value)))
    result=p.collect(registry([cfg for cfg in configs if cfg.enabled]),at)
    with p.store.transaction() as c:
        after={r['provider_id']:json.loads(r['state_json']) for r in c.execute('SELECT * FROM ne_provider_state')}
    notify_changes(before,after,at)
    return result


def notify_changes(before,after,at):
    """Only provider transitions, private durable Admin outbox, no public send."""
    from ai_operations import enqueue
    from .model import fingerprint,timestamp
    for pid,value in after.items():
        if pid not in BLOCKERS:continue
        old=before.get(pid,{})
        signature=lambda v:(v.get('status'),v.get('error'),v.get('http_status'))
        if signature(old)==signature(value):continue
        status=value.get('status','unknown')
        label='ENABLED' if status in {'ok','no_new','not_modified'} else 'DISABLED' if status=='disabled' else 'DEGRADED'
        key='news_provider_transition:'+pid+':'+fingerprint([timestamp(at),signature(value)])
        enqueue(key,'AI-Trader Admin\nNews provider: '+pid+' — '+label+
                ('\nTimezone: UTC — provider_specific_operational_rule' if pid=='investing' else '')+
                '\nStatus: '+status+'\nReason: '+str(value.get('error') or 'none')+
                '\nHTTP: '+str(value.get('http_status') or 'n/a')+
                '\nNext check: '+str(value.get('next_at') or 'n/a'))
