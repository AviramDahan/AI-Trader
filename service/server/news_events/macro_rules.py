"""Narrow headline rules for observed macro false negatives. No provider I/O."""
import re

BENCHMARK = re.compile(r'^\s*(?:SOFR|secured overnight financing rate)(?=\s*:|\s+\d|\s+(?:at|is|was|rose|fell|rises|falls)\b|$)', re.I)
US = re.compile(r'(?<!\w)(?:US|U\.S\.|United States)(?!\w)', re.I)
CENTRAL_BANK = re.compile(r'^(?:ECB|Fed|Federal Reserve|Bank of England|BoE)(?:[’\']s)?\s+(?:(?:President|Gov\.?|Governor)\s+)?[A-Za-z-]+\s*:', re.I)
ECONOMIC_FACT = re.compile(r'\b(?:inflation|interest rates?|policy rates?|monetary policy|unemployment|Treasury yields?|growth)\b', re.I)
TREASURY_RATE = re.compile(r'^(?:U\.?S\.?\s+)?(?:two|ten|2|10)[ -]year\s+Treasury\s+yield\b', re.I)
FUEL_EXPORT_BAN = re.compile(r'^Russia\b.{0,90}\bextend\b.{0,10}\bdiesel export ban\b',re.I)


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
    return bool(BENCHMARK.search(title) or diplomatic_talks(title)
        or (CENTRAL_BANK.search(title) and ECONOMIC_FACT.search(title))
        or TREASURY_RATE.search(title) or attributed_fuel_export_plan(title))


def factual_macro_title(title):
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
