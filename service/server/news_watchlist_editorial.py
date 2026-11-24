"""Editorial checks for the public news-only watchlist topic."""
import re
from dataclasses import dataclass, replace
from datetime import timedelta

from news_analyst_routing import enabled as analyst_enabled, is_analyst_update
from news_quality import source_facts
from news_public_importance import enabled as strict_quality, source_importance
from operation_mode import news_only
from telegram_topics import thread_id_for_event


SUBORDINATE = re.compile(r'\b(?:after|as|because|amid|following|with|on news|unlike|versus|compared (?:with|to)|trades? like|hint:)\b', re.I)
PRICE_MOVE = re.compile(r'\b(?:stocks?|shares?|futures|rall(?:y|ies|ied)|stock market|wall street|market wrap|'
                        r'gold|bullion|bitcoin|S&P|Nasdaq|Dow|surges?|jumps?|climbs?|soars?|rises?|falls?|sinks?|slumps?|drops?|gains?|trades?)\b', re.I)
MARKET_WRAP = re.compile(r'^(?:stocks? (?:market today|stage|rally)|wall street|US (?:stocks?|stock futures)|'
                         r'(?:top |latest )?(?:midday|market) stories|Dow,|S&P 500,|Nasdaq,)|'
                         r'\b(?:US market wrap|market recap|charts to watch|stocks? that explain today[’\']s market)\b', re.I)
COMMENTARY = re.compile(r"\b(?:here(?:'|’)s (?:why|what)|things to consider|net worth|a retiree|"
                        r'paper losses|no choice|stock did after|real winner|market cap comparison)\b', re.I)
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
                         r'calls? (?:on|for)|sources? (?:say|tells?)|according to|denies?|wants? (?:to|the)|expects? to|to (?:reinstate|reappoint)|propos\w*)\b', re.I)
FOLLOW_UP = re.compile(r'\b(?:committee|probe|investigat\w*|export controls?|blacklist\w*|updated guidance)\b', re.I)


# A headline must state an action and a specific object. Unknown objects and
# provisional reports are ineligible for cross-source event deduplication.
_GUIDANCE = re.compile(
    r'\b(?P<action>raises?|raised|lifts?|boosts?|cuts?|lowers?|lowered|reduces?|'
    r'withdraws?|withdrew|reaffirms?|maintains?)\b'
    r'(?P<scope>[^;:.]{0,65}?)\b(?P<kind>guidance|outlook|forecast)\b', re.I)
_PERIOD = re.compile(r'\b(?:(?:fiscal\s+)?q([1-4])\s*(?:fy\s*)?(20\d{2})|fy\s*(20\d{2})|'
                     r'(?:full[- ]year|fiscal year)\s*(20\d{2})|(20\d{2})\s+(?:full[- ]year|fiscal year))\b', re.I)
_REGULATION = re.compile(
    r"\b(?P<actor>u\.?s\.? commerce department|commerce department|bis|u\.?s\.?|"
    r"united states|department of justice|doj|ftc|sec|european commission|fda)\s+"
    r"(?P<action>imposes?|expands?|lifts?|removes?|blocks?|approves?|rejects?|grants?|"
    r"revokes?|denies?|opens?|launches?|files?|rules?)\b(?P<object>[^;]{1,160})", re.I)
_EXPORT = re.compile(r'\bexport (?:controls?|restrictions?|curbs?|bans?|licen[cs]es?)\b', re.I)
_EXPORT_PRODUCT = re.compile(r'\b(?:H20|H200|H100|A100|B200|GB200|GB300|MI300X)\b', re.I)
_EXPORT_MARKET = re.compile(r'\b(?:china|russia|united arab emirates|saudi arabia)\b', re.I)
_DEAL = re.compile(
    r"\b(?P<action>agrees? to (?:buy|acquire|purchase)|signs? (?:a |an )?(?:deal|agreement) to acquire|"
    r"completes? (?:its |the )?(?:acquisition|purchase) of|closes? (?:its |the )?(?:acquisition|purchase) of)"
    r"\s+(?P<target>[A-Z][\w&.\-'’]*(?:\s+[A-Z][\w&.\-'’]*){0,4})\b")
_VALUE = re.compile(r'(?<!\w)(?:[$€£]\s*\d[\d,]*(?:\.\d+)?\s*(?:trillion|billion|million|bn|m)?|'
                    r'\d[\d,]*(?:\.\d+)?\s*(?:percent|%))(?!\w)', re.I)
_SCOPE_CHANGE = re.compile(r'\b(?:revised|amended|expanded scope|new exception|effective date|'
                           r'starts? on|takes? effect|exempts?|carve[- ]out|supersedes?|corrects?)\b', re.I)
_RELATION = re.compile(r'\b(?:to (?:buy|purchase|supply|ship|sell|stop buying|stop supplying)|'
                       r'(?:buys?|purchases?|orders?|sources?|ships?|supplies?|sells?|'
                       r'cancels? (?:an? |its )?orders? (?:for|from))|'
                       r'(?:ban|controls?|blacklist\w*|investigat\w*)\b.{0,65}\b(?:over|for|on|of))\b', re.I)
_RELATION_OBJECT = re.compile(r'\b(?:chips?|graphics processors?|gpus?|accelerators?|cloud (?:capacity|services?)|'
                              r'memory|hbm\w*|contract|orders?|acquisition|stake|licenses?|data cent(?:er|re)s?)\b', re.I)
_OPINION_LEAD = re.compile(r'\b(?:says?|said|sees?|called|calls?)\b.{0,130}\b(?:positive|negative|winner|'
                           r'worst|best|cheap(?:er)?|expensive|overrated|underrated|great|bullish|bearish)\b', re.I)
_NON_COMPANY = re.compile(r'\b(?:affairs? during talks|personal affairs?|bought .{0,28} calls|'
                          r'net worth|options bet|paper gain|hedge fund manager|national treasure)\b', re.I)
_CONTEXT_ONLY = re.compile(r'\b(?:on hopes|tracking|following|riding|in sympathy with|on the heels of|'
                           r'sparked by|lifts? (?:chip stocks|equities))\b', re.I)


@dataclass(frozen=True)
class MaterialEvent:
    identity: tuple[str, ...]
    values: frozenset[str]


def _period(text):
    match = _PERIOD.search(text)
    if match:
        quarter, q_year, *fy = match.groups()
        return f'{q_year}-q{quarter}' if quarter else next(value for value in fy if value)


def _value_set(text):
    values = {re.sub(r'[\s,]', '', value.casefold().replace('percent', '%')) for value in _VALUE.findall(text)}
    return frozenset(re.sub(r'(?<=\d)(?:billion|bn)$', 'b', re.sub(r'(?<=\d)million$', 'm', value))
                     for value in values)


def _material_key(title, subject):
    if UNCONFIRMED.search(title) or _SCOPE_CHANGE.search(title):
        return None
    # Exclude commentary on the price reaction from the reported event itself.
    lead = re.split(r'\b(?:shares?|stock)\s+(?:soars?|rises?|jumps?|falls?|drops?|surges?)\b',
                    title, maxsplit=1, flags=re.I)[0]
    if match := _GUIDANCE.search(lead):
        scope = f'{match["scope"]} {lead[match.end():]}'
        period = _period(scope)
        if subject(lead[:match.start()]) and period:
            verb = match['action'].casefold()
            direction = ('up' if verb.startswith(('rais', 'lift', 'boost')) else
                         'down' if verb.startswith(('cut', 'lower', 'reduc')) else
                         'withdraw' if verb.startswith(('withdr', 'withd')) else 'reaffirm')
            metrics = [metric for metric, pattern in (
                ('capex', r'capital expenditures?|capex'), ('eps', r'eps|earnings per share'),
                ('revenue', r'revenue|sales'), ('margin', r'margins?'),
                ('profit', r'profits?')) if re.search(r'\b(?:'+pattern+r')\b', scope, re.I)]
            # Ambiguous metric and articles with more than one reported metric
            # have no safe identity for a semantic duplicate.
            if len(metrics) == 1 and not re.search(r'\band\b', match['scope'], re.I):
                return MaterialEvent(('guidance', direction, period, metrics[0]), _value_set(scope))
    if match := _REGULATION.search(lead):
        obj = match['object']
        export = _EXPORT.search(obj)
        products = tuple(sorted({value.casefold() for value in _EXPORT_PRODUCT.findall(obj)}))
        markets = tuple(sorted({value.casefold() for value in _EXPORT_MARKET.findall(obj)}))
        if export and products and markets and subject(obj):
            actor = re.sub(r'[^a-z ]', '', match['actor'].casefold())
            actor = {'united states': 'us', 'us commerce department': 'bis',
                     'commerce department': 'bis', 'department of justice': 'doj'}.get(actor, actor)
            verb = match['action'].casefold().rstrip('s')
            action = {'remove': 'lift'}.get(verb, verb)
            if 'licen' not in export[0].casefold():
                category = 'ban' if 'ban' in export[0].casefold() else 'restriction'
                return MaterialEvent(('export', actor, action, category, *products, *markets), _value_set(obj))
    if match := _DEAL.search(lead):
        target = match['target'].casefold().rstrip('.')
        if subject(lead[:match.start()]) and not subject(match['target']) and not re.search(
                r'\b(?:assets|business|unit|division|stake|shares|from)\b', lead[match.end():], re.I):
            phase = 'closed' if match['action'].startswith(('complete', 'close')) else 'signed'
            return MaterialEvent(('acquisition', phase, target), _value_set(lead))
    return None


def _direct_consequence(title, subject):
    """Permit another lead issuer only where the watched issuer is in the action."""
    for action in _RELATION.finditer(title):
        before, after = title[:action.start()], title[action.end():]
        if _CONTEXT_ONLY.search(before):
            continue
        # Scope to the same action. Trailing cause/comparison and a new clause
        # cannot make a product or counterparty part of this transaction.
        clause = re.split(r'[;.!?]|\b(?:as|after|amid|while|compared|unlike|following)\b',
                          after, maxsplit=1, flags=re.I)[0]
        if subject(clause) and _RELATION_OBJECT.search(clause):
            return True
    # Some sources lead with a reaction and then state a distinct issuer
    # investment in a second sentence. Retain that fact only with an amount
    # and an explicit purchase of equity; a valuation or an options trade is
    # not evidence of the company's investment.
    for clause in re.split(r'[;]|(?<=[.!?])\s+', title):
        investment = re.search(
            r'\b(?:paid|invested|invests)\s+[$€£]\s*\d[\d,.]*\s*(?:million|billion|mn|bn)'
            r'\s+(?:for|in)\s+[^;]+\b(?:stock|equity|stake|shares)\b', clause, re.I)
        if investment and subject(clause[:investment.start()]):
            return True
    return False


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
    def subject(text):
        return news_pipeline._headline_verifies_ticker(ticker, company or '', text, watchlist=True)

    lead, *tail = SUBORDINATE.split(title, maxsplit=1)
    if MARKET_WRAP.search(title):
        return 'watchlist_market_recap', None
    separate_fact = bool(FOLLOW_UP.search(title) and subject(title))
    material = _material_key(title, subject)
    has_material_event = material is not None
    if material:
        excerpt = source_facts(row)['source_excerpt']
        if _SCOPE_CHANGE.search(excerpt):
            # The source supplied terms that are not part of the event key.
            material = None
        elif excerpt:
            material = replace(material, values=material.values | _value_set(excerpt))
    consequence = bool(has_material_event or _direct_consequence(title, subject))
    comparison = re.search(r'\b(?:trades? like|compared (?:with|to)|unlike)\b', title, re.I)
    if tail and (PRICE_MOVE.search(lead) or comparison) and not subject(lead) and not consequence:
        return 'watchlist_incidental_subject', None
    if (COMMENTARY.search(title) or _OPINION_LEAD.search(title) or _NON_COMPANY.search(title)) and not consequence:
        return 'watchlist_commentary', None
    leadership = _leadership_key(title)
    context = _CONTEXT_ONLY.search(title)
    if (context and PRICE_MOVE.search(title[:context.start()]) and not subject(title[:context.start()])
            and not consequence and not separate_fact and not leadership):
        return 'watchlist_incidental_subject', None
    if not leadership and PRICE_ONLY.search(lead) and not (separate_fact or consequence or source_importance(title)[0]):
        return 'watchlist_price_only', None
    return None, material or (MaterialEvent(leadership, frozenset()) if leadership else None)

def already_covered(conn, issuer_tickers, key, row, now, *, company, delivery_id=None):
    """Reuse the durable personal ledger and only live/sent outbox versions.

    A bounded recent comparison uses explicit facts, not scores or title
    similarity. A cancelled or definitively failed alert never owns the event.
    """
    after = (now - timedelta(hours=18)).isoformat().replace('+00:00', 'Z')
    slots = ','.join('?' for _ in issuer_tickers)
    before = ' AND o.id<?' if delivery_id is not None else ''
    params = (*issuer_tickers, after, row['id'], *((delivery_id,) if delivery_id is not None else ()))
    candidates = conn.execute(f"""SELECT n.title,n.source_facts_json,a.ticker FROM scanner_news_watchlist_alerts a
      JOIN scanner_news n ON n.id=a.news_id
      JOIN scanner_telegram_outbox o
        ON o.dedupe_key='watchlist-news:' || a.news_id || ':' || a.event_version || ':' || a.ticker
      WHERE a.event_version=COALESCE(NULLIF(n.content_hash,''),'v1') AND a.ticker IN ({slots}) AND a.created_at>=? AND
        a.news_id<>?
        AND o.event_type='watchlist_news' AND o.status IN ('pending','retry','sending','sent'){before}
      ORDER BY a.created_at DESC,o.id DESC LIMIT 160""", params)
    for candidate in candidates:
        candidate = dict(candidate)
        reason, event = decision(candidate, candidate['ticker'], company)
        if not reason and event and event.identity == key.identity and key.values <= event.values:
            return True
    return False
