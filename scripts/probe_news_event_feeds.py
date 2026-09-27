"""Explicit isolated RSS availability probe. No AI/DB writes/article scraping.

Only the official Investing RSS-reader feed and GlobeNewswire public RSS are
probed. This checks access, NOT permission for AI use/public redistribution.
PR Newswire/Benzinga/TipRanks require licensing/credentials and are not probed.
"""
import argparse
from dataclasses import replace
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time
import dotenv

dotenv.load_dotenv=lambda *a,**kw:False
for name in list(os.environ):
    if name.startswith(('OPENROUTER_','TELEGRAM_','OLLAMA_','NEWS_','STOCK_SCANNER_')) or name=='DATABASE_URL':
        os.environ.pop(name,None)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'service/server'))
from news_events.providers import DEFAULT_CONFIGS,RSSProvider,ProviderFailure

parser=argparse.ArgumentParser();parser.add_argument('--network',action='store_true')
args=parser.parse_args()
if not args.network:parser.error('Explicit --network required for the two public RSS availability requests')
for cfg in DEFAULT_CONFIGS:
    if cfg.provider_id not in ('investing','globenewswire'):continue
    now=datetime.now(timezone.utc);start=time.monotonic()
    try:
        provider=RSSProvider(replace(cfg,enabled=True,rights='internal_review'))
        response=provider.fetch({},now)
        parsed=0;invalid=0;errors=[]
        for item in response['items']:
            try:provider.normalize(item,now);parsed+=1
            except (ValueError,TypeError,KeyError) as exc:
                invalid+=1
                if not errors:errors.append({'type':type(exc).__name__,'timestamp':str(item.get('published_at'))[:80],
                                             'reason':str(exc)[:100]})
        result={'status':'parsed','items':len(response['items']),'normalized':parsed,'invalid':invalid,'first_metadata_error':errors}
    except ProviderFailure as exc:
        result={'status':'unavailable','reason':exc.reason,'http_status':exc.http_status,'retry_after':exc.retry_after}
    except Exception as exc:
        result={'status':'unavailable','reason':type(exc).__name__}
    print(json.dumps({'provider':cfg.provider_id,'at':now.isoformat(),'seconds':round(time.monotonic()-start,3),
                      'ai_calls':0,'public_messages':0,**result}))
