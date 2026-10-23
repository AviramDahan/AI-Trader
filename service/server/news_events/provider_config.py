"""Provider enablement requires an explicit, retained license approval reference.

Configuration disablement is separate from retained access failures. Secrets
come from server environment only. An RSS URL alone never constitutes a license.
"""
import json
import os
from dataclasses import replace
from .providers import DEFAULT_CONFIGS, registry

BLOCKERS={
 'investing':'activation_boundary_required',
 'globenewswire':'provider_not_enabled',
 'prnewswire':'provider_not_enabled',
 'benzinga':'free_news_api_credential_missing; official_rss_unavailable',
 'tipranks':'enterprise_market_news_contract_endpoint_schema_and_credentials_required',
}


def disabled_reason(provider_id):
    """Explain current configuration, never invent a vendor/payment response."""
    enabled=set(filter(None,os.getenv('NEWS_EVENTS_PROVIDERS','').split(',')))
    if provider_id not in enabled:return 'provider_not_enabled'
    approvals=json.loads(os.getenv('NEWS_EVENTS_PROVIDER_APPROVALS','{}'))
    if not approvals.get(provider_id):return 'approval_reference_missing'
    return BLOCKERS.get(provider_id,'provider_configuration_required')


def suspended(previous,reason):
    # Snapshot once, not once per poll; preserve every cursor/replay fence and
    # consumed recovery marker. The visible disabled reason is not the old HTTP
    # failure, whose complete state remains available for exact restoration.
    saved=previous.get('disabled_resume_state',previous) if previous.get('status')=='disabled' else previous
    retained=saved if isinstance(saved,dict) else {}
    return {**retained,'status':'disabled','error':reason,'http_status':None,'terminal':True,
            'next_at':None,'disabled_resume_state':saved}


def resumed(previous):
    saved=previous.get('disabled_resume_state')
    known={'ok','no_new','not_modified','degraded','rate_limited','requires_configuration'}
    if isinstance(saved,dict) and (not saved or saved.get('status') in known):return dict(saved)
    # Old binaries discarded disabled checkpoints. Their absence cannot prove
    # a clean/new provider or replenish a recovery allowance. Keep the original
    # row for diagnosis; legitimate operator verification is required, not a
    # fabricated reconstruction from today's configuration or old headlines.
    retained={k:v for k,v in previous.items() if k!='disabled_resume_state'}
    return {**retained,'status':'requires_configuration','resume_state_unavailable':True,
            'error':'provider_resume_state_unavailable','terminal':True,'next_at':None}


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
            previous=before.get(cfg.provider_id,{})
            if cfg.enabled:
                if previous.get('status')!='disabled':continue
                value=resumed(previous)
            else:value=suspended(previous,disabled_reason(cfg.provider_id))
            c.execute('INSERT INTO ne_provider_state VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET state_json=excluded.state_json',
                (cfg.provider_id,json.dumps(value)))
    result=p.collect(registry([cfg for cfg in configs if cfg.enabled]),at)
    with p.store.transaction() as c:
        after={r['provider_id']:json.loads(r['state_json']) for r in c.execute('SELECT * FROM ne_provider_state')}
    notify_changes(before,after,at)
    return result


def _next_check_notice(pid,value):
    """Presentation only: persisted next_at is not a terminal retry promise."""
    if not value.get('terminal'):
        return '\nNext check: '+str(value.get('next_at') or 'n/a')
    if value.get('status')=='disabled':
        return '\nNext check: not scheduled (provider disabled)'
    if (pid=='prnewswire' and value.get('http_status')==301
            and value.get('error')=='http_error' and value.get('last_success')):
        return ('\nNext check: not scheduled as a routine retry (terminal provider state; '
                'operator review required if the conditional allowance is unavailable)'
                '\nRecovery: a single conditional original-official-feed 301 probe requires '
                'current approval, a due saved next-check, at least one-hour cooldown and '
                'an unused verified-incident allowance; timing and success are not guaranteed.')
    if (pid in {'prnewswire','globenewswire'} and value.get('http_status')==403
            and value.get('error')=='http_error' and value.get('last_success')):
        # Do not duplicate or run recover_terminal here. Actual approval,
        # cooldown and consumed-probe fences remain the collector's decision.
        return ('\nNext check: no routine retry (terminal provider state)'
                '\nRecovery: a single conditional 403 probe requires current approval, '
                'at least one-hour cooldown and an unused recovery allowance; '
                'timing is not guaranteed.')
    return '\nNext check: not scheduled (terminal provider state; operator review required)'


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
                _next_check_notice(pid,value))
