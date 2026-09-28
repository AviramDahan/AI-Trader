"""News-feed-only Yahoo adapter; scanner/final-review input remains unchanged."""
import re
import time
from datetime import datetime, timezone
import requests


def fetch_news(ticker, company, max_age_hours):
    from stock_scanner import YAHOO_SEARCH_URL, USER_AGENT
    session=requests.Session();session.trust_env=False
    with session:
        response=session.get(YAHOO_SEARCH_URL,params={'q':ticker,'quotesCount':1,'newsCount':10},
                             headers={'User-Agent':USER_AGENT},timeout=20)
        response.raise_for_status()
        return normalize_news(response.json(),ticker,company,max_age_hours,time.time())


def normalize_news(payload,ticker,company,max_age_hours,at):
    items=[]
    for row in payload.get('news') or []:
        try:published=int(row['providerPublishTime'])
        except (KeyError,TypeError,ValueError):continue
        related=[str(v).upper().replace('.','-') for v in row.get('relatedTickers') or []]
        link,title=str(row.get('link') or ''),str(row.get('title') or '').strip()
        if not title or not link.startswith('https://') or ticker not in related:continue
        age=(at-published)/3600
        if age<-.1 or age>max_age_hours:continue
        company_words={v.lower() for v in re.findall(r'[A-Za-z]{3,}',company)}
        company_match=bool(company_words.intersection(re.findall(r'[a-z]{3,}',title.lower())))
        relevance=min(1.0,.65+(.2 if company_match else 0)+.15*max(0,1-age/max_age_hours))
        item={'title':title[:300],'publisher':str(row.get('publisher') or 'Yahoo Finance')[:100],
              'url':link,'published_at':datetime.fromtimestamp(published,timezone.utc).isoformat(),
              'age_hours':round(age,2),'relevance':round(relevance,3),
              'provider_tickers':related,'tickers':related}
        if isinstance(row.get('summary'),str) and row['summary'].strip():item['source_excerpt']=row['summary'].strip()[:2000]
        items.append(item)
    items.sort(key=lambda v:v['published_at'],reverse=True)
    return items[:5]
