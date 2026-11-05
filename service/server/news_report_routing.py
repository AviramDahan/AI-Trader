"""Presentation destination only. Never admits news, assigns a ticker or calls AI.

Durable news types/keys retain their existing publisher fencing and recovery
meaning. All eligibility checks run before the effective send-time destination.
"""
import json
import os
import re

NEWS_TYPES = frozenset({'market_news','stock_news','position_news','watchlist_news',
                        'watchlist_news_correction','correction'})
REPORT_PREFIX = '📊 דיווח תוצאות — '
CONTROLS = re.compile('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]')
PERIOD = re.compile(r'\b(?:Q[1-4]|[1-4]Q|quarter\w*|annual|fiscal year|full.year)\b|רבעו|לשנת',re.I)
METRIC = re.compile(r'\b(?:EPS|EBITDA|(?:earnings|loss) per share|net (?:profit|income|loss)|'
    r'operating (?:profit|income|loss)|revenues?|rev|sales)\b|'
    r'רווח(?:ים)?\s+(?:למניה|נקי|תפעולי)|הפסד(?:ים)?\s+(?:למניה|נקי|תפעולי)|הכנסות',re.I)
RESULTS = re.compile(r'\b(?:financial results|quarterly (?:financial )?results|annual (?:financial )?results)\b|'
    r'תוצאות(?:יה|יו)?\s+(?:הכספיות|לרבעון|הרבעון|רבעון|לשנת)',re.I)
ACTUAL = re.compile(r'\b(?:reports?|reported|posts?|posted|released)\b|דיווח\w*|מדווח\w*|פרסמ\w*|הציג\w*|רשמ\w*',re.I)
PAST = re.compile(r'\b(?:reported|posted|released)\b|דיווחה|דיווחו|פרסמה.*תוצאות|הציגה|רשמה',re.I)
PREVIEW = re.compile(r'\b(?:will report|to report|scheduled|earnings preview|earnings calendar|'
    r'announces? (?:the )?date|date (?:for|of)|expects? earnings|expected earnings)\b|'
    r'תדווח|תפרסם|צפויה לפרסם|מועד פרסום|לוח דוחות|צפי לתוצאות|לקראת הדוחות',re.I)
MACRO_REVENUE = re.compile(r'\b(?:tax|government|budget) revenue\w*\b|הכנסות\s+(?:המדינה|הממשלה|ממסים)',re.I)


def is_company_report(title, excerpt=''):
    title=title if isinstance(title,str) else ''
    excerpt=excerpt if isinstance(excerpt,str) else ''
    text=CONTROLS.sub('',title+'\n'+excerpt)[:12000]
    # A trader interpretation mentioning earnings cannot reclassify macro news.
    text=re.split(r'משמעות אפשרית לסוחר\s*\(AI\):|פרשנות AI:',text,maxsplit=1)[0]
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if not lines:return False
    headline=next((line.split('כותרת:',1)[1] for line in lines if line.startswith('כותרת:')),lines[0])
    if headline.startswith(REPORT_PREFIX):return True
    if '?' in headline:return False  # Editorial question is not a results release.
    # The topic follows the article's subject. A share-price reaction or an
    # explanatory metrics article is news, even when earnings explain it.
    first=headline.split(';',1)[0]
    financial=re.compile(r'\b(?:earnings|EPS|revenues?|sales|profit|net income|financial results)\b',re.I)
    share=re.search(r'\b(?:shares|stock)\b',first,re.I)
    price_action=r'\b(?:ris(?:e[sd]?)|rose|surges?|soars?|falls?|fell|drops?|sinks?|plunges?|jumps?|down|up|declin(?:es?|ed)|little changed)\b'
    if (share and not financial.search(first[:share.start()])
            and re.search(price_action,first[share.end():share.end()+65],re.I)):return False
    move=re.search(price_action+r'.{0,18}\d+(?:\.\d+)?\s*%',first,re.I)
    if move and not financial.search(first[:move.start()]):return False
    if re.search(r'\b(?:how|what) key metrics\b|האם.{0,40}כדאי',headline,re.I):return False
    if (re.search(r'\b(?:clinical|trial|election|poll|exam|sports|acquisition|merger|appoints?)\b|'
                  r'תוצאות ניסוי|תוצאות בחירות|מינוי מנכ',headline,re.I)
            and not re.search(r'financial results|תוצאות כספיות',headline,re.I)):return False
    if re.search(r'\b(?:GDP|CPI|PPI|PCE|import prices|export prices|retail sales|jobless|unemployment)\b|'
                 r'תוצר מקומי|מדד המחירים|מחירי היבוא|מחירי הייצוא|מכירות קמעונאיות',headline,re.I):return False
    if PREVIEW.search(headline) and not PAST.search(headline):return False
    # Calls/transcripts and future presentation notices are not a fresh result.
    if re.search(r'\b(?:earnings call transcript|(?:conference|earnings) call highlights|'
                 r'(?:financial results|earnings) conference(?: call)?)\b',headline,re.I):return False
    if (re.search(r'\b(?:earnings|EPS)\b',headline,re.I) and
            re.search(r'\b(?:could|might|may|will|would|expected to|expects? to)\b.{0,60}\b(?:beat|miss)',headline,re.I)):
        return False
    if re.search(r'\banalyst\b|price target|מחיר יעד',headline,re.I) and not ACTUAL.search(headline):return False
    if MACRO_REVENUE.search(text):return False
    if RESULTS.search(headline):return True
    # Compact actual wire results often omit "reports", e.g. Q3 adjusted
    # earnings/revenue rise. Only an explicit period + financial metric +
    # realized result verb qualifies; future guidance alone does not.
    first_clause=headline.split(';',1)[0]
    future=bool(re.search(r'\b(?:could|might|may|will|would|expected to|expects? to)\b|'
        r'\b(?:revenue|sales|EPS|earnings)\s+(?:forecast|guidance|outlook)\b',first_clause,re.I))
    if PERIOD.search(first_clause) and not future:
        if (re.search(r'\b(?:reports?|announces?|posts?|released)\b',first_clause,re.I)
                and re.search(r'\bresults\b',first_clause,re.I)):return True
        if (re.search(r'\b(?:earnings|EPS|revenues?|sales|net (?:income|profit)|profit|funds from operations)\b',first_clause,re.I)
                and re.search(r'\b(?:beats?|miss(?:es)?|surpass(?:es)?|exceeds?|surges?|ris(?:e[sd]?)|'
                    r'increases?|declines?|falls?|drops?|grew|grows?|flat|up|down)\b',first_clause,re.I)):
            return True
    if PERIOD.search(headline) and ACTUAL.search(headline) and re.search(r'\bearnings\b|רווחים|הפסדים',headline,re.I):return True
    if (PERIOD.search(headline) and re.search(r'\bearnings\b.{0,30}\b(?:beat(?:s)?|miss(?:es)?)\b.{0,30}'
            r'\b(?:estimates?|expectations?|consensus|forecasts?)\b',headline,re.I)):return True
    # Generic body disclaimers cannot lend financial-results identity to an
    # unrelated headline. A body-only report needs its own actual period/result
    # clause; model interpretation was already stripped above.
    factual=[line for line in lines if not re.search(r'forward.looking|actual (?:financial )?results (?:may|could|might) differ|'
        r'גורמי סיכון|מידע צופה פני עתיד',line,re.I)]
    actual_body=any(PERIOD.search(line) and ACTUAL.search(line) and (METRIC.search(line) or RESULTS.search(line))
                    and not (PREVIEW.search(line) and not PAST.search(line))
                    for line in factual)
    if actual_body:return True
    if not (PERIOD.search(headline) and METRIC.search(headline)):return False
    if ACTUAL.search(headline):return True
    # Compact wire headlines: SYN 3Q ADJ EPS $2.10, EST $2.00.
    return bool(re.search(r'\b(?:EPS|EBITDA|REVENUES?|REV|SALES|LOSS PER SHARE|NET PROFIT|OPERATING PROFIT)'
        r'\s*[:$€£]?\s*-?\d',headline,re.I))


def report_event(event):
    """Current original facts only; attached older topics cannot lend identity."""
    if not isinstance(event,dict) or not isinstance(event.get('title'),str):return False
    if is_company_report(event['title'],event.get('source_excerpt','')):return True
    return any(isinstance(source,dict) and source.get('title')==event['title']
               and is_company_report(source.get('title'),source.get('source_excerpt',''))
               for source in event.get('sources',[]))


def delivery_type(kind, message, *, analyst_update=None):
    if kind in NEWS_TYPES and is_company_report(message):return 'company_report'
    from news_analyst_routing import BROAD_TYPES, enabled, is_analyst_update
    if kind in BROAD_TYPES and enabled() and (analyst_update is True or
            (analyst_update is None and is_analyst_update(message))):return 'analyst_update'
    return kind


def prior_report_delivery(cursor, row):
    """Exact source/version convergence, under the existing sole Telegram lease.

    No fuzzy matching across unrelated stories, new facts or issuers. A known
    sent/ambiguous peer is never resent through another original news topic.
    Claimed rows are processed in ID order by the caller.
    """
    key=row['dedupe_key']
    if key.startswith('canonical:'):
        link=cursor.execute('SELECT event_id,version FROM ne_outbox WHERE dedupe_key=?',(key,)).fetchone()
        if not link:return None
        peers=cursor.execute('''SELECT o.id,o.status,o.last_error FROM ne_outbox n
            JOIN scanner_telegram_outbox o ON o.dedupe_key=n.dedupe_key
            WHERE n.event_id=? AND n.version=? AND o.id!=? ORDER BY o.id LIMIT 33''',
            (link['event_id'],link['version'],row['id'])).fetchall()
        if key.startswith('canonical:general-v1:'):
            # Existing general-story keys already encode exact evidence/time.
            # Check all original destinations when those routes now converge;
            # keep saved keys unchanged, including pre-release queued messages.
            from news_events.general_news import publication_keys
            from telegram_topics import thread_id_for_event
            event=cursor.execute('SELECT body_json FROM ne_events WHERE event_id=?',
                                 (link['event_id'],)).fetchone()
            if event:
                body=json.loads(event['body_json'])
                destinations={thread_id_for_event(kind) for kind in (*NEWS_TYPES,'company_report','analyst_update')}
                destinations.update(thread_id_for_event('stock_news',stock_direction=direction)
                                    for direction in ('positive','negative'))
                keys=sorted({k for destination in destinations
                    for k in publication_keys(body,link['version'],
                        [os.getenv('TELEGRAM_CHAT_ID','').strip(),destination])})
                if len(keys)>32:return 'company_report_peer_limit'
                if keys:
                    peers=[*peers,*cursor.execute('SELECT id,status,last_error FROM scanner_telegram_outbox WHERE id!=? AND dedupe_key IN ('+
                        ','.join('?' for _ in keys)+')',(row['id'],*keys)).fetchall()]
    else:
        parts=key.split(':')
        families=('market-news','news','watchlist-news','stock-news')
        if (len(parts)<3 or parts[0] not in families or not parts[1].isdigit()
                or not re.fullmatch(r'[0-9a-f]{20}|[0-9a-f]{64}|v1',parts[2])):return None
        clauses=[];args=[]
        for family in families:
            base=family+':'+parts[1]+':'+parts[2]
            clauses.append('(dedupe_key=? OR dedupe_key LIKE ?)');args.extend((base,base+':%'))
        peers=cursor.execute('SELECT id,status,last_error FROM scanner_telegram_outbox WHERE id!=? AND ('+
            ' OR '.join(clauses)+') ORDER BY id LIMIT 33',(row['id'],*args)).fetchall()
    if len(peers)>32:return 'company_report_peer_limit'
    for peer in peers:
        if peer['status']=='sent':return 'company_report_already_sent'
        if peer['status']=='sending' and peer['id']<row['id']:
            return 'company_report_peer_delivery_unknown'
        try:error=json.loads(peer['last_error'] or '{}')
        except (ValueError,TypeError):error={}
        if isinstance(error,dict) and (error.get('reason')=='delivery_unknown_manual_review' or
                (isinstance(error.get('http_status'),int) and error['http_status']>=500)):
            return 'company_report_peer_delivery_unknown'
    return None
