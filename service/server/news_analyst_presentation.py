"""Short source-backed analyst notices; no inference, scoring or routing."""
import re

from news_analyst_routing import CONTROLS


def compact_parts(title, summary, tickers=''):
    """Keep the headline and complementary translated facts verbatim.

    Omit repeated headline text, never guess which free-form summary clauses
    contain a firm, rating, target or caveat. Boilerplate and interpretation are
    removed by callers at their known template boundaries. License credits and
    publication times are appended separately by the existing caller.
    """
    title = CONTROLS.sub('', str(title or '')).strip()
    summary = CONTROLS.sub('', str(summary or '')).strip()
    if not title:
        title, summary = summary, ''
    parts = ['📊 '+title]
    if tickers:
        parts.append('מניות: '+tickers)
    if summary == title:
        summary = ''
    elif title:
        # Remove only an exact full headline followed by sentence punctuation.
        # Do not split abbreviations, compare bags of words or normalize numbers.
        summary = re.sub(r'^'+re.escape(title.rstrip('.!?'))+r'[.!?](?:\s+|$)', '', summary, count=1)
    if summary:
        parts.append(summary)
    return parts
