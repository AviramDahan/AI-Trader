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


def has_reported_results(title, excerpt=''):
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
    # Wire headlines may express a forecast as "sees [company] 4Q revenue
    # up 70%". The later period/metric/up tokens do not make it an actual.
    forecast_clause = headline.split(';', 1)[0]
    forecast = re.search(r'\b(?:sees?|projects?|forecasts?|expects?|anticipates?|predicts?)\b', forecast_clause, re.I)
    if (forecast and not ACTUAL.search(forecast_clause[:forecast.start()])
            and PERIOD.search(forecast_clause) and METRIC.search(forecast_clause[forecast.end():])):
        return False
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
    if (PERIOD.search(headline) and re.search(r'\bearnings\b',headline,re.I)
            and ACTUAL.search(text) and has_financial_values(text)):return True
    if headline.startswith('📊 תוצאות פעילות החברה') and ('התוצאות בפועל' in text or 'נוכחי:' in text) and has_financial_values(text):return True
    if not (PERIOD.search(headline) and METRIC.search(headline)):return False
    if ACTUAL.search(headline):return True
    # Compact wire headlines: SYN 3Q ADJ EPS $2.10, EST $2.00.
    return bool(re.search(r'\b(?:EPS|EBITDA|REVENUES?|REV|SALES|LOSS PER SHARE|NET PROFIT|OPERATING PROFIT)'
        r'\s*[:$€£]?\s*-?\d',headline,re.I))


def results_only_enabled():
    return os.getenv('TELEGRAM_COMPANY_REPORTS_RESULTS_ONLY_ENABLED','false').lower()=='true'


def has_financial_values(title,excerpt=''):
    """Visible reported values and a stated period, not dates/stock targets.

    This checks presence, not truth or units conversion. Source fidelity and
    current-version analysis remain the caller's existing authority.
    """
    text=CONTROLS.sub('',str(title or '')+'\n'+str(excerpt or ''))[:12000]
    text=re.split(r'משמעות אפשרית לסוחר\s*\(AI\):|פרשנות AI:',text,maxsplit=1)[0]
    period=r'\b(?:Q[1-4]|[1-4]Q)\b|\b(?:first|second|third|fourth)[ -]quarter\b|'
    period+=r'רבעון.{0,15}(?:ראשון|שני|שלישי|רביעי|[1-4])|תקופת הדיווח\s*:\s*20\d{2}|'
    period+=r'(?:FY|fiscal|fiscal year|full.year|לשנת)\s*20\d{2}|quarter ended.{0,40}20\d{2}'
    if not re.search(period,text,re.I):return False
    field=re.compile(METRIC.pattern+r'|תזרים(?: מזומנים)? מפעילות שוטפת|תזרים מזומנים|מרווח(?: תפעולי)?',re.I)
    value=re.compile(r'[$€£]\s*-?\d[\d,.]*|\b-?\d[\d,.]*\s*(?:%|[MB]\b|USD\b|EUR\b|GBP\b|million\b|billion\b|cents?\b|מיליון|מיליארד|דולר|אירו|ליש|סנט)',re.I)
    expectation=re.compile(r'\b(?:expect(?:s|ed)?|estimate[sd]?|consensus|forecast|guidance)\b|צפי|ציפיות|תחזית|צפוי(?:ה|ים|ות)?|משוער(?:ת)?',re.I)
    prior=r'\b(?:(?:prior|previous)(?:[ -](?:year|quarter|period))?|last[ -](?:year|quarter)|a year ago)\b|בשנה שעברה|ברבעון הקודם|בתקופה הקודמת|אשתקד'
    comparison=re.compile(r'\b(?:versus|vs\.?|compared (?:with|to)|as expected)\b|לעומת|בהשוואה',re.I)
    lines=re.split(r'[\n;]|,(?!\d)|(?<=[.!?])\s+',text)
    expected_section=False
    for index,line in enumerate(lines):
        if re.search(r'ציפיות האנליסטים|^\s*(?:analyst expectations|consensus expectations)',line,re.I):expected_section=True;continue
        if re.search(r'התוצאות בפועל|^\s*actual results',line,re.I):expected_section=False;continue
        if expected_section:continue
        if re.match(r'^\s*\W*(?:expected|forecast|guidance|consensus|צפי|תחזית|ציפיות)(?:\b|ל)',line,re.I):continue
        if index+1<len(lines) and re.match(r'\s*(?:בפועל|נוכחי|actual|current)\s*:',lines[index+1],re.I):line+=' '+lines[index+1]
        for match in field.finditer(line):
            before=line[max(0,match.start()-35):match.start()]
            if re.search(r'\b(?:expect(?:s|ed)?|estimated|consensus|forecast|guidance)(?:\s+(?:for|of|adjusted|adj|non-gaap|gaap)){0,3}\s*$|'
                         r'(?:צפי|תחזית|ציפיות|צפוי|משוער)(?:\s*(?:ל|של))?\s*$|(?:'+prior+r')\s*[:\-]?\s*$',before,re.I):continue
            after=line[match.end():match.end()+100]
            number=value.search(after)
            if not number and re.fullmatch(r'EPS|(?:earnings|loss) per share',match[0],re.I):
                number=re.match(r'\s*[:=]?\s*-?\d+\.\d+\b',after)
            if not number:continue
            between=after[:number.start()]
            # Qualifiers after the amount matter too. Stop at an explicit
            # comparison so another period/consensus value cannot relabel the
            # current result ("EPS 2.10 versus expected EPS 2.00").
            suffix=comparison.split(after[number.end():],maxsplit=1)[0]
            next_field=field.search(suffix)
            if next_field:suffix=suffix[:next_field.start()]
            if expectation.search(between) or expectation.search(suffix) or re.search(prior,between,re.I):continue
            percent_change=('%' in number[0]
                and re.search(r'\b(?:increas\w*|decreas\w*|grew|grows?|rose|ris\w*|fell|falls?|declin\w*)\b|על[וה]|ירד|גדל',between,re.I)
                and re.match(r'\s*(?:from|over)\s+(?:the\s+)?(?:'+prior+r')',suffix,re.I))
            if re.search(prior,suffix,re.I) and not percent_change:continue
            if not re.search(r'\b(?:shares?|stock|price)\b|מחיר|מניות|מניית',between,re.I):return True
    return False


def is_company_report(title,excerpt=''):
    if not results_only_enabled():return has_reported_results(title,excerpt)
    # A historical presentation prefix does not prove that figures exist.
    title=CONTROLS.sub('',str(title or '')).replace(REPORT_PREFIX,'',1)
    return has_reported_results(title,excerpt) and has_financial_values(title,excerpt)


def report_event(event):
    """Current original facts only; attached older topics cannot lend identity."""
    if not isinstance(event,dict) or not isinstance(event.get('title'),str):return False
    if is_company_report(event['title'],event.get('source_excerpt','')):return True
    return any(isinstance(source,dict) and source.get('title')==event['title']
               and is_company_report(source.get('title'),source.get('source_excerpt',''))
               for source in event.get('sources',[]))


def report_for_presentation(event,result):
    return report_event(event) and (not results_only_enabled() or
        is_company_report(result.get('title_he'),result.get('summary_he','')))


def report_for_outbox(row):
    """Strict mode binds report identity to exact retained source AND payload."""
    if not results_only_enabled() or row.get('event_type') not in NEWS_TYPES:return None
    from database import get_db_connection
    from news_events.control import state
    try:
        with get_db_connection() as c:
            key=row.get('dedupe_key','');control=state(c)
            if key.startswith('canonical:'):
                if control['mode']!='canonical':return False
                link=c.execute('SELECT * FROM ne_outbox WHERE dedupe_key=?',(key,)).fetchone()
                if (not link or link['epoch']!=control['epoch'] or
                    {'market_news':'market_news','important_stock_news':'stock_news','portfolio_watchlist':'position_news'}.get(link['topic'])!=row['event_type']):return False
                event=c.execute('SELECT * FROM ne_events WHERE event_id=?',(link['event_id'],)).fetchone()
                if not event or event['evidence_version']!=link['version'] or event['status']!='analyzed' or event['reason']:return False
                result=c.execute("SELECT result_json FROM ne_analysis WHERE event_id=? AND version=? AND status='done'",(link['event_id'],link['version'])).fetchone()
                return bool(result and report_for_presentation(json.loads(event['body_json']),json.loads(result['result_json'])))
            p=key.split(':')
            if (control['mode']!='phase1' or len(p) not in (3,4) or p[0] not in ('market-news','stock-news','news','watchlist-news')
                    or not p[1].isdigit() or int(p[1])<=0 or not re.fullmatch(r'[0-9a-f]{20}|[0-9a-f]{64}|v1',p[2])):return False
            family={'market_news':'market-news','stock_news':'stock-news','position_news':'news','watchlist_news':'watchlist-news'}.get(row['event_type'])
            if p[0]!=family or (family=='market-news' and len(p)!=3) or (family!='market-news' and (len(p)!=4 or not p[3])):return False
            record=c.execute('SELECT * FROM scanner_news WHERE id=?',(int(p[1]),)).fetchone()
            if not record:return False
            record=dict(record);audit=c.execute('SELECT content_version FROM news_publication_audit WHERE news_id=?',(record['id'],)).fetchone()
            version=audit['content_version'] if audit else record.get('content_hash') or 'v1'
            if p[2]!=version or record.get('analysis_status') not in ('analyzed','public_translated') or record.get('analysis_error') or record.get('duplicate_of'):return False
            if record.get('analysis_status')=='analyzed' and record.get('quality_version') not in (2,3):return False
            if family=='stock-news':
                selected=p[3].split(',');verified=json.loads(record.get('verified_tickers_json') or 'null')
                if (not isinstance(verified,list) or any(not isinstance(t,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',t) for t in verified)
                        or selected!=sorted(set(selected)) or not set(selected)<=set(verified)):return False
            facts=json.loads(record.get('source_facts_json') or '{}')
            return (isinstance(facts,dict) and is_company_report(record.get('title'),facts.get('source_excerpt',''))
                    and is_company_report(row.get('message')))
    except (ValueError,TypeError,KeyError):return False


def delivery_type(kind, message, *, analyst_update=None, company_report=None):
    if kind in NEWS_TYPES and (company_report is True or (company_report is None and is_company_report(message))):return 'company_report'
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
