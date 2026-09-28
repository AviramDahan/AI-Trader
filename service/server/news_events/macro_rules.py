"""Narrow headline rules for observed macro false negatives. No provider I/O."""
import re

BENCHMARK = re.compile(r'^\s*(?:SOFR|secured overnight financing rate)\b', re.I)
US = re.compile(r'(?<!\w)(?:US|U\.S\.|United States)(?!\w)', re.I)


def diplomatic_talks(title):
    # Require named state counterparties and an actual reported negotiation,
    # not every mention of Iran, a company negotiation, or generic geopolitics.
    return bool(US.search(title) and re.search(r'\bIran\b',title,re.I)
        and re.search(r'\b(?:mediators?|official|source)\b',title,re.I)
        and re.search(r'\b(?:hold|held|resume|resumed|scheduled)\s+(?:separate\s+)?talks\b',title,re.I))


def market_headline(title):
    return bool(BENCHMARK.search(title) or diplomatic_talks(title))


def factual_macro_title(title):
    # A named benchmark + an explicit measured rate is concrete data.
    if BENCHMARK.search(title):
        return bool(re.search(r'\b\d+(?:\.\d+)?\s*%',title))
    if diplomatic_talks(title):return True
    # An attributed central-bank policy statement may be conditional. It is
    # evidence of the statement, NOT proof that the predicted change will occur.
    return bool(re.search(r'^(?:Bank of England|BoE)[’\']s\s+[A-Za-z-]+\s+(?:says|said|warns)\b',title,re.I)
        and re.search(r'\b(?:rates?|inflation)\b',title,re.I)
        and re.search(r'\b(?:rise|fall|increase|decrease|higher|lower)\b',title,re.I))
