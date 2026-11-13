"""Short source-backed analyst notices; no inference, scoring or routing."""
import re

from news_analyst_routing import CONTROLS


def _clear_target_comparison(text):
    if not re.search(r'מחיר(?:י)?\s+ה?יעד|יעד\s+(?:המחיר|מחיר)', text):
        return text
    return re.sub(r'(\d[\d,.]*\s+דולר)\s+מתוך\s+(\d[\d,.]*\s+דולר)',
                  r'\1 (לעומת \2 קודם)', text)


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
    parts = ['📊 '+_clear_target_comparison(title)]
    if tickers:
        parts.append('מניות: '+tickers)
    if summary == title:
        summary = ''
    elif title:
        # Remove only an exact full headline followed by sentence punctuation.
        # Do not split abbreviations, compare bags of words or normalize numbers.
        summary = re.sub(r'^'+re.escape(title.rstrip('.!?'))+r'[.!?](?:\s+|$)', '', summary, count=1)
    if summary:
        parts.append(_clear_target_comparison(summary))
    return parts
