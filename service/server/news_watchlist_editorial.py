"""Editorial checks for the public news-only watchlist topic."""
import re
from datetime import timedelta

from news_analyst_routing import enabled as analyst_enabled, is_analyst_update
from news_public_importance import enabled as strict_quality, source_importance
from operation_mode import news_only
from telegram_topics import thread_id_for_event


SUBORDINATE = re.compile(r'\b(?:after|as|because|amid|following|with|on news|unlike|versus|compared (?:with|to)|trades? like|hint:)\b', re.I)
PRICE_MOVE = re.compile(r'\b(?:stocks?|shares?|futures|rall(?:y|ies|ied)|stock market|wall street|market wrap|'
                        r'S&P|Nasdaq|Dow|surges?|jumps?|climbs?|soars?|rises?|falls?|sinks?|slumps?|drops?|gains?|trades?)\b', re.I)
MARKET_WRAP = re.compile(r'^(?:stocks? (?:market today|stage|rally)|wall street|US (?:stocks?|stock futures)|'
                         r'(?:top |latest )?(?:midday|market) stories|Dow,|S&P 500,|Nasdaq,)|'
                         r'\b(?:US market wrap|market recap|charts to watch|stocks? that explain today[’\']s market)\b', re.I)
COMMENTARY = re.compile(r"\b(?:here(?:'|’)s (?:why|what)|things to consider|net worth|a retiree|"
                        r'paper losses|no choice|stock did after)\b', re.I)
PRICE_ONLY = re.compile(r'\b(?:shares?|stocks?) (?:extend(?:s|ed)?|surge(?:s|d)?|jump(?:s|ed)?|'
                        r'climb(?:s|ed)?|rall(?:y|ies|ied)|rise(?:s)?|rose|fall(?:s)?|fell|'
                        r'plunge(?:s|d)?|drop(?:s|ped)?|sink(?:s)?|sank|close(?:s|d)?|'
                        r'(?:is|are) (?:up|down))\b|\b(?:premarket|pre-market) gains?\b|'
                        r'\b(?:add(?:s|ed)?|gain(?:s|ed)?)\b.{0,55}\b(?:market (?:value|cap))\b|'
                        r'\bstock delivers? (?:the )?biggest gain\b', re.I)
ROLE = r'(?:chief executive(?: officer)?|CEO)'
NAME = r'[A-Za-z][A-Za-z.\'-]*(?:\s+[A-Za-z][A-Za-z.\'-]*){0,2}'
RETURN = re.compile(r'\b(?:reinstat(?:es?|ed|ement)|reappoint(?:s|ed|ment))\s+(?P<name>'+NAME+r')\s+as\s+'
                    r'(?:(?:its|the|new|president)[, ]+)*'+ROLE, re.I)
RETURN_SUBJECT = re.compile(r'(?P<name>(?:[A-Z][A-Za-z.\'-]+\s+){0,2}[A-Z][A-Za-z.\'-]+)\s+'
                            r'(?i:(?:has )?return(?:s|ed)?|is back|was reinstated|reinstated)\s+'
                            r'(?i:as|to (?:the )?role of)\s+(?:[A-Za-z][\w.\'’-]*\s+){0,3}(?i:'+ROLE+r')\b')
RETURN_POSSESSIVE = re.compile(r'\b(?P<name>'+NAME+r')[’\']s\s+(?:return|reinstatement)\s+as\s+'+ROLE, re.I)
UNCONFIRMED = re.compile(r'\b(?:could|might|may|urges?|pressure\w*|reportedly|rumou?r\w*|speculation|'
                         r'calls? (?:on|for)|wants? (?:to|the)|expects? to|to (?:reinstate|reappoint)|propos\w*)\b', re.I)
FOLLOW_UP = re.compile(r'\b(?:committee|probe|investigat\w*|export controls?|blacklist\w*|updated guidance)\b', re.I)


def enabled():
    return news_only() and strict_quality()


def _headline(row):
    title = str(row.get('title') or '')[:1000]
    title = re.sub(r'\s*\|FJ\s*$', '', title, flags=re.I)
    return re.sub(r'^\s*(?:(?:[!‼❗]+\s*)|(?:JUST IN|BREAKING)\s*:\s*|\$[A-Z]{1,8}\s*[-—:]\s*)+', '', title, flags=re.I).strip()


def _leadership_key(title):
    # A new committee, new scope of an inquiry, or a distinct government action
    # is a follow-up fact, even if the headline also repeats the appointment.
    if UNCONFIRMED.search(title) or FOLLOW_UP.search(title):
        return None
    match = RETURN.search(title) or RETURN_SUBJECT.search(title) or RETURN_POSSESSIVE.search(title)
    if not match:
        return None
    name = match['name'].split()[-1].strip(".-'").casefold()
    return ('ceo_return', name) if len(name) >= 3 else None


def decision(row, ticker, company):
    """Return a reason to skip the watchlist, and an optional exact event family."""
    import news_pipeline

    title = _headline(row)
    if analyst_enabled() and thread_id_for_event('analyst_update') and is_analyst_update(title):
        return 'watchlist_analyst_destination', None
    lead, *tail = SUBORDINATE.split(title, maxsplit=1)
    if MARKET_WRAP.search(title):
        return 'watchlist_market_recap', None
    comparison = re.search(r'\b(?:trades? like|compared (?:with|to)|unlike)\b', title, re.I)
    if tail and (PRICE_MOVE.search(lead) or comparison) and not news_pipeline._headline_verifies_ticker(
            ticker, company, lead, watchlist=True):
        return 'watchlist_incidental_subject', None
    if COMMENTARY.search(title):
        return 'watchlist_commentary', None
    key = _leadership_key(title)
    if not key and PRICE_ONLY.search(lead) and not (FOLLOW_UP.search(title) or source_importance(title)[0]):
        return 'watchlist_price_only', None
    return None, key


def already_covered(conn, issuer_tickers, key, row, now, *, company, delivery_id=None):
    """Reuse the durable personal ledger and only live/sent outbox versions.

    A bounded recent comparison uses explicit facts, not scores or title
    similarity. A cancelled or definitively failed alert never owns the event.
    """
    after = (now - timedelta(hours=18)).isoformat().replace('+00:00', 'Z')
    slots = ','.join('?' for _ in issuer_tickers)
    before = ' AND o.id<?' if delivery_id is not None else ''
    params = (*issuer_tickers, after, row['id'], *((delivery_id,) if delivery_id is not None else ()))
    candidates = conn.execute(f"""SELECT n.title,a.ticker FROM scanner_news_watchlist_alerts a
      JOIN scanner_news n ON n.id=a.news_id
      JOIN scanner_telegram_outbox o
        ON o.dedupe_key='watchlist-news:' || a.news_id || ':' || a.event_version || ':' || a.ticker
      WHERE a.ticker IN ({slots}) AND a.created_at>=? AND a.news_id<>?
        AND o.event_type='watchlist_news' AND o.status IN ('pending','retry','sending','sent'){before}
      ORDER BY a.created_at DESC,o.id DESC LIMIT 160""", params)
    for candidate in candidates:
        candidate = dict(candidate)
        if _leadership_key(_headline(candidate)) == key and decision(candidate, candidate['ticker'], company) == (None, key):
            return True
    return False
