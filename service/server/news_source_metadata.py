"""News source ledger only: retain evidence for audit, never infer identity."""
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def retain(item, previous=None, *, collected_at):
    previous=previous or {}
    current={k:item[k] for k in ('title','publisher','published_at','original_url','url',
        'source_excerpt','provider_tickers','relatedTickers','summary','categories','exchange','cik') if k in item}
    for key in ('provider_tickers','relatedTickers'):
        if key in current:
            values=current[key] if isinstance(current[key],(list,tuple)) else []
            current[key]=[v for v in values if isinstance(v,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]{0,9}',v)]
    for key in ('url','original_url'):
        if key not in current:continue
        try:
            parts=urlsplit(current[key])
            if parts.username or parts.password:raise ValueError('credential_in_url')
            query=[(k,v) for k,v in parse_qsl(parts.query) if k.lower() not in
                   {'token','apikey','api_key','key','access_token','password','secret','signature'}]
            current[key]=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),''))
        except (ValueError,TypeError):current.pop(key,None)
    # An incomplete repeat must not erase the supplied feed summary. A changed
    # headline is a new observation; never lend the old text to that headline.
    if current.get('title')==previous.get('title') and not str(current.get('source_excerpt') or '').strip():
        current['source_excerpt']=previous.get('source_excerpt','')
    current['collected_at']=collected_at
    current['first_observation']=previous.get('first_observation') or {k:v for k,v in current.items()}
    return current
