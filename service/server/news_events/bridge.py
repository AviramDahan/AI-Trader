"""Explicit legacy-data boundary. Does not import/start existing workers."""
from .engine import Policy


def scanner_identity_catalog(scanner_cache,sec_mapping=None):
    """Use the scanner's existing union; attach CIK only from official mapping.

    Caller supplies read-only snapshots. No ticker feeds or per-company crawl.
    The existing scanner cache has company names but does NOT contain CIKs.
    """
    universe={ticker:dict(value) for ticker,value in scanner_cache['members'].items()}
    issuers={}
    for cik,tickers in (sec_mapping or {}).get('all_cik_to_tickers',{}).items():
        for ticker in tickers:issuers.setdefault(ticker,set()).add(str(cik).lstrip('0'))
    for ticker,data in universe.items():
        values=issuers.get(ticker,set())
        if len(values)==1:data['cik']=values.pop()
    return universe


def effective_policy(feed_settings,market_relevance,market_age_hours,universe_age_hours,max_age_hours):
    """Pass effective deployed settings explicitly, never silently lower gates."""
    return Policy(personal_relevance=feed_settings['alert_min_relevance'],
        stock_relevance=feed_settings['broad_alert_min_relevance'],market_relevance=market_relevance,
        max_age_hours=max_age_hours,market_age_hours=market_age_hours,
        universe_age_hours=universe_age_hours)
