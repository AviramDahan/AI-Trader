"""Provider enablement requires an explicit, retained license approval reference.

Default blocked states are based on the 2026-09-27 access/terms review. Secrets
come from server environment only. An RSS URL alone never constitutes a license.
"""
import json
import os
from dataclasses import replace
from .providers import DEFAULT_CONFIGS, registry

BLOCKERS={
 'investing':'source_timezone_missing; syndication_workflow_permission_unconfirmed',
 'globenewswire':'cloud_http_response_timeout_after_successful_dns_tls; feed_license_confirmation_required',
 'prnewswire':'written_owner_permission_for_redistribution_and_ai_workflow_required',
 'benzinga':'licensed_news_api_token_and_redistribution_ai_scope_required',
 'tipranks':'enterprise_market_news_contract_endpoint_schema_and_credentials_required',
}


def configured():
    approvals=json.loads(os.getenv('NEWS_EVENTS_PROVIDER_APPROVALS','{}'))
    enabled=set(filter(None,os.getenv('NEWS_EVENTS_PROVIDERS','').split(',')))
    configs=[]
    for original in DEFAULT_CONFIGS:
        pid=original.provider_id
        # A license cannot resolve missing source timestamps/contracts.
        supported=pid not in {'investing','tipranks'}
        live=pid in enabled and bool(approvals.get(pid)) and supported
        configs.append(replace(original,enabled=live,rights='approved' if live else 'review_required',
            credential=os.getenv('NEWS_'+pid.upper()+'_API_KEY','')))
    return configs


def collect(p,at):
    from .model import timestamp
    configs=configured()
    with p.store.transaction(True) as c:
        for cfg in configs:
            if cfg.enabled:continue
            value={'status':'disabled','error':BLOCKERS[cfg.provider_id],'next_at':None}
            c.execute('INSERT INTO ne_provider_state VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET state_json=excluded.state_json',
                (cfg.provider_id,json.dumps(value)))
    return p.collect(registry([cfg for cfg in configs if cfg.enabled]),at)
