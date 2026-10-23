"""Narrow headline rules for observed macro false negatives. No provider I/O."""
import re

BENCHMARK = re.compile(r'^\s*(?:SOFR|secured overnight financing rate)(?=\s*:|\s+\d|\s+(?:at|is|was|rose|fell|rises|falls)\b|$)', re.I)
US = re.compile(r'(?<!\w)(?:US|U\.S\.|United States)(?!\w)', re.I)
CENTRAL_BANK = re.compile(r'^(?:ECB|Fed|Federal Reserve|Bank of England|BoE)(?:[’\']s)?\s+(?:(?:President|Gov\.?|Governor)\s+)?[A-Za-z-]+\s*:', re.I)
ECONOMIC_FACT = re.compile(r'\b(?:inflation|interest rates?|policy rates?|monetary policy|unemployment|Treasury yields?|growth)\b', re.I)
TREASURY_RATE = re.compile(r'^(?:U\.?S\.?\s+)?(?:two|ten|2|10)[ -]year\s+Treasury\s+yield\b', re.I)
FUEL_EXPORT_BAN = re.compile(r'^Russia\b.{0,90}\bextend\b.{0,10}\bdiesel export ban\b',re.I)

# Two observed complete data-bulletin forms. A reported ACTUAL and both literal
# comparisons are mandatory; an economic keyword, preview, or company name is
# not enough. The relay decoration is optional and supplies no source authority.
_RELEASE_NUMBER = r'[+-]?\d{1,3}(?:\.\d{1,4})?'
_RELEASE_PREFIX = r'\s*(?:[‼❗]\ufe0f?\s*)?(?:BREAKING:\s*)?'
_RELEASE_SUFFIX = r'(?:\s+\$MACRO\|FJ)?\s*'
FORMAL_PMI_RELEASE = re.compile(
    _RELEASE_PREFIX+r'(?:FRANCE|FRENCH)\s+MANUFACTURING\s+PMI\s+FLASH\s+ACTUAL\s+'
    +_RELEASE_NUMBER+r'\s+\(FORECAST\s+'+_RELEASE_NUMBER
    +r',\s+PREVIOUS\s+'+_RELEASE_NUMBER+r'\)'+_RELEASE_SUFFIX,re.I)
FORMAL_RETAIL_RELEASE = re.compile(
    _RELEASE_PREFIX+r'(?:UK|U\.K\.|UNITED KINGDOM)\s+RETAIL\s+SALES\s+(?:YOY|Y/Y|MOM|M/M)\s+ACTUAL\s+'
    +_RELEASE_NUMBER+r'%\s+\(FORECAST\s+'+_RELEASE_NUMBER
    +r'%,\s+PREVIOUS\s+'+_RELEASE_NUMBER+r'%\)'+_RELEASE_SUFFIX,re.I)

# Policy-rate releases are macro subjects, not unverified company identities.
# Keep an explicit jurisdiction/central-bank vocabulary: arbitrary proper nouns
# (commercial banks included) cannot turn their own rates into policy decisions.
_RATE_JURISDICTION = (
    r'(?:Argentina|Argentinian|Australia|Australian|Brazil|Brazilian|Canada|Canadian|'
    r'Chile|Chilean|China|Chinese|Colombia|Colombian|Czech(?: Republic|ia)?|'
    r'Denmark|Danish|Eurozone|Euro Area|Hungary|Hungarian|Iceland|Icelandic|'
    r'India|Indian|Indonesia|Indonesian|Israel|Israeli|Japan|Japanese|'
    r'Malaysia|Malaysian|Mexico|Mexican|New Zealand|Norway|Norwegian|'
    r'Peru|Peruvian|Philippines|Philippine|Poland|Polish|Romania|Romanian|'
    r'Russia|Russian|Saudi Arabia|South Africa|South African|South Korea|South Korean|'
    r'Sweden|Swedish|Switzerland|Swiss|Taiwan|Taiwanese|Thailand|Thai|'
    r'Turkey|Turkish|United Kingdom|UK|U\.K\.|United States|US|U\.S\.)')
_RATE_CENTRAL_BANK = (
    r'(?:ECB|European Central Bank|Fed|Federal Reserve|BoE|Bank of England|'
    r'Bank of Canada|Bank of Japan|Bank of Russia|Central Bank of Russia|'
    r'Reserve Bank of Australia|Reserve Bank of New Zealand|Reserve Bank of India|'
    r'People[\x27\u2019]s Bank of China|PBOC|Banco Central do Brasil|Bank of Israel|'
    r'Swiss National Bank|Norges Bank|Riksbank|Bank of Korea|Central Bank of Turkey)')
_RATE_AUTHORITY = r'(?:'+_RATE_JURISDICTION+'|'+_RATE_CENTRAL_BANK+')'
_POLICY_RATE = r'(?:(?:(?:key|policy|benchmark)(?: interest)?|interest|cash|repo|bank) rate)'
_RATE_PERCENT = r'[+-]?[0-9]{1,3}(?:\.[0-9]{1,4})?%'
FORMAL_RATE_DECISION = re.compile(
    _RELEASE_PREFIX+_RATE_AUTHORITY+r'\s+'+_POLICY_RATE+r' DECISION ACTUAL\s+'
    +_RATE_PERCENT+r'\s+\(FORECAST\s+'+_RATE_PERCENT+r',\s+PREVIOUS\s+'
    +_RATE_PERCENT+r'\)'+_RELEASE_SUFFIX,re.I)
REPORTED_RATE_DECISION = re.compile(
    _RELEASE_PREFIX+_RATE_AUTHORITY+r'\s+(?:'
    r'(?:holds|held|keeps|kept|maintains|maintained|leaves|left)\s+'
    r'(?:(?:its|the)\s+)?'+_POLICY_RATE+r'(?: unchanged)? at\s+'+_RATE_PERCENT+'|'
    r'(?:raises|raised|hikes|hiked|cuts|cut|lowers|lowered)\s+'
    r'(?:(?:its|the)\s+)?'+_POLICY_RATE+r' to\s+'+_RATE_PERCENT
    +r'(?: from\s+'+_RATE_PERCENT+r')?)'
    r'(?:,\s+as expected)?'+_RELEASE_SUFFIX,re.I)


def reported_rate_decision(title):
    """A complete, bounded reported policy-rate fact, not primary verification.

    A literal ACTUAL/FORECAST/PREVIOUS tuple or an actual decision verb and
    explicit rate are required. No preview, arbitrary bank/company, inferred
    release period or inferred source authority is admitted by this rule. The
    existing rights, freshness, analysis and publication gates remain mandatory.
    """
    return bool(type(title) is str and len(title)<=400
                and all(c.isprintable() for c in title)
                and (FORMAL_RATE_DECISION.fullmatch(title)
                     or REPORTED_RATE_DECISION.fullmatch(title)))


def reported_economic_release(title):
    """A complete literal bulletin, not publication approval or primary proof.

    These forms do not state the reported month/year. Leave that period UNKNOWN;
    do not manufacture a release identity, dedupe anchor, or source verification.
    Existing rights, freshness, review, materiality and relevance still apply.
    """
    return bool(FORMAL_PMI_RELEASE.fullmatch(title) or FORMAL_RETAIL_RELEASE.fullmatch(title))

# Match the subject and its reported movement, not a benchmark/metal word
# elsewhere in a company headline. Bare company shares, Inc. and extra company
# name words cannot fit between the anchored subject and the movement verb.
INDEX_SUBJECT = (r'(?:Nasdaq(?:\s+(?:Composite|100))?|S&P\s*500|'
                 r'Dow Jones(?:\s+Industrial Average)?|FTSE\s*100|DAX|'
                 r'Nikkei\s*225|Hang Seng|Russell\s*2000|Stoxx\s*600)'
                 r'(?:\s+index)?')
COMMODITY_SUBJECT = (r'(?:spot\s+)?(?:gold|silver|copper|oil|crude oil|'
                     r'Brent(?:\s+crude(?:\s+oil)?)?|WTI(?:\s+crude(?:\s+oil)?)?|natural gas)'
                     r'(?:\s+prices?)?')
EXTREME = (r'(?:(?:a|an|the)\s+)?(?:record|all[- ]time|session|'
           r'(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)[- ]'
           r'(?:day|week|month|year))\s+(?:high|low)\b')
MEASURED_LEVEL = r'(?:[$\u20ac\u00a3]\s*)?\d+(?:[,.]\d+)*(?![\w,.-])'
REPORTED_MOVEMENT = re.compile(
    r'^\s*(?:'+INDEX_SUBJECT+'|'+COMMODITY_SUBJECT+r')\s+(?:'
    r'(?:rises?|rose|falls?|fell|rebounds?|rebounded|gains?|gained|drops?|dropped|'
    r'slides?|slid|slips?|slipped|climbs?|climbed|retreats?|retreated|'
    r'declines?|declined|rallies|rallied|surges?|surged)'
    r'(?=$|[,;:]|\s+(?:\d|[$\u20ac\u00a3]|as\b|after\b|amid\b|on\b|to\b|with\b|'
    r'while\b|despite\b|following\b|by\b|from\b|again\b|today\b|yesterday\b|overnight\b|'
    r'above\b|below\b|nearly\b|about\b|more\b|less\b))|'
    r'(?:nears?|neared)\s+'+EXTREME+'|'
    r'(?:hits?|hit|reaches?|reached|touches?|touched)\s+(?:'+EXTREME+'|'+MEASURED_LEVEL+r')|'
    r'(?:closes?|closed|opens?|opened|settles?|settled|trades?|traded)\s+'
    r'(?:higher|lower|up|down|(?:at|above|below)\s+'+MEASURED_LEVEL+r')\b)', re.I)
MOVEMENT_NONFACT = re.compile(
    r'\?|\b(?:may|might|could|should|would|will|shall|can|if|unless|whether|likely|poised|'
    r'forecast\w*|predict\w*|expect\w*|project\w*|outlook|preview|opinion|analysis|why|how|guide|'
    r'subscribe|sponsored|promotion\w*|advertisement|secret)\b|'
    r'\b(?:tomorrow|tonight|next\s+(?:week|weekends?|month|year|quarter|'
    r'monday|tuesday|wednesday|thursday|friday|saturday|sunday)|by\s+20\d{2}|'
    r'set to|buy now|sign up|trade idea|investment advice)\b', re.I)
MOVEMENT_CORPORATE = re.compile(
    r'\b(?:earnings|EPS|revenue|dividend|buyback|repurchase|merger|acquisition|acquires?|'
    r'CEO|CFO|quarterly results|financial results|price target|rating|upgrades?|downgrades?)\b', re.I)


def reported_market_movement(title):
    """A narrow reported price/index move, never a forecast or company action.

    This only admits the original headline to existing evidence/quality checks;
    it supplies no missing price, numerical change, cause or publication approval.
    """
    return bool(REPORTED_MOVEMENT.search(title) and not MOVEMENT_NONFACT.search(title)
                and not MOVEMENT_CORPORATE.search(title))


def attributed_fuel_export_plan(title):
    return bool(FUEL_EXPORT_BAN.search(title)
                and re.search(r'\b(?:through (?:January|February|March|April|May|June|July|August|September|October|November|December)|another month)\b',title,re.I))


def diplomatic_talks(title):
    # Require named state counterparties and an actual reported negotiation,
    # not every mention of Iran, a company negotiation, or generic geopolitics.
    return bool(US.search(title) and re.search(r'\bIran\b',title,re.I)
        and re.search(r'\b(?:mediators?|official briefed on the negotiations)\b',title,re.I)
        and re.search(r'\b(?:hold|held|resume|resumed|scheduled)\s+(?:separate\s+)?talks\b',title,re.I))


def market_headline(title):
    # Central-bank inflation outlooks are macro, not a company's guidance.
    return bool(reported_economic_release(title) or reported_rate_decision(title) or reported_market_movement(title) or BENCHMARK.search(title) or diplomatic_talks(title)
        or (CENTRAL_BANK.search(title) and ECONOMIC_FACT.search(title))
        or TREASURY_RATE.search(title) or attributed_fuel_export_plan(title))


def factual_macro_title(title):
    if reported_economic_release(title):return True
    if reported_rate_decision(title):return True
    if reported_market_movement(title):return True
    # A named benchmark + an explicit measured rate is concrete data.
    if BENCHMARK.search(title):
        return bool(re.search(r'\b\d+(?:\.\d+)?\s*%',title))
    if diplomatic_talks(title):return True
    if attributed_fuel_export_plan(title):
        # Evidence of the attributed plan, not a claim the ban is already law.
        return True
    if TREASURY_RATE.search(title):
        return bool(re.search(r'\b(?:reaches?|rises?|falls?|hits?)\s+(?:to\s+)?\d+(?:\.\d+)?\s*%',title,re.I))
    if CENTRAL_BANK.search(title) and ECONOMIC_FACT.search(title):
        # A reported outlook with an explicit direction/comparison, not every
        # utterance by a central banker or a headline announcing a live speech.
        return bool(re.search(r'\b(?:higher|lower|rise|fall|increase|decrease)\b',title,re.I)
            and re.search(r'\b(?:outlook|expect\w*|forecast\w*|\d{4}|than)\b',title,re.I))
    # An attributed central-bank policy statement may be conditional. It is
    # evidence of the statement, NOT proof that the predicted change will occur.
    return bool(re.search(r'^(?:Bank of England|BoE)[’\']s\s+[A-Za-z-]+\s+(?:says|said|warns)\b',title,re.I)
        and re.search(r'\b(?:rates?|inflation)\b',title,re.I)
        and re.search(r'\b(?:rise|fall|increase|decrease|higher|lower)\b',title,re.I))
