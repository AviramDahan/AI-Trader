"""Publication rules for the Telegram news-only channel."""
import re

from news_analyst_presentation import complementary_text


_QUALIFIER = re.compile(
    r'\b(?:preliminary report|unconfirmed|rumou?rs?|reportedly|according to|'
    r'sources say|citing (?:people|sources))\b|^\s*דיווח ראשוני|^\s*לפי דיווח',
    re.I,
)
_HEBREW_QUALIFIER = re.compile(r'(?:דיווח ראשוני|לפי (?:דיווח|מקורות)|על פי (?:דיווח|מקורות)|טרם אומת)')
_NAMED_SOURCE = re.compile(r'\b(?:according to|reported by)\s+(Reuters|Bloomberg|WSJ|The Wall Street Journal|CNBC)\b', re.I)


def qualified_copy(original, title, summary):
    """Keep preliminary or attributed claims within a visibly qualified headline."""
    if not _QUALIFIER.search(original or ''):
        return title, summary
    named = _NAMED_SOURCE.search(original)
    if named and named[1].casefold() not in title.casefold():
        title = f'לפי דיווח של {named[1]}: {title}'
    elif not _HEBREW_QUALIFIER.search(title):
        prefix = 'דיווח ראשוני: ' if re.search(r'preliminary|unconfirmed|rumou?r|דיווח ראשוני', original, re.I) else 'לפי דיווח: '
        title = prefix + title
    # A standalone AI paraphrase can shed the attribution or expand the claim.
    return title, ''


def analyst_subject_symbol(original):
    """Read an explicit issuer symbol before the broker action, when supplied."""
    subject = re.split(
        r'\b(?:raises?|lowers?|cuts?|boosts?|upgrades?|downgrades?|initiates?|'
        r'price target|target price)\b', original or '', maxsplit=1, flags=re.I,
    )
    if len(subject) != 2:
        return ''
    # In "Issuer beat estimates while Broker raises ...", the clause preceding
    # "while" identifies the issuer. For "Broker raises Issuer (XYZ) ...",
    # examine the object following the action, never the broker prefix.
    before, after = subject
    if re.search(r'\bwhile\b', before, re.I):
        issuer_text = re.split(r'\bwhile\b', before, maxsplit=1, flags=re.I)[0]
    else:
        issuer_text = re.split(r'\b(?:to|from|at)\b', after, maxsplit=1, flags=re.I)[0]
    tickers = re.findall(r'\(([A-Z][A-Z0-9.-]{0,9})\)|\$([A-Z][A-Z0-9.-]{0,9})\b', issuer_text)
    symbols = {a or b for a, b in tickers}
    if not symbols and re.match(r"\s*(?:Walt )?Disney(?:'s)?\b", issuer_text, re.I):
        return 'DIS'
    return next(iter(symbols)) if len(symbols) == 1 else ''


def watchlist_parts(symbol, title, summary, *, headline_only):
    """Use one line for a headline and keep genuinely additional article detail."""
    title = ' '.join(title.split())
    lines = [f'{symbol} · {title}' if symbol else title]
    if headline_only:
        return lines
    # Keep the concise source-backed facts already produced by translation.
    # Some outputs repeat the headline as a separate line without punctuation.
    paragraphs = [' '.join(line.split()) for line in str(summary or '').splitlines() if line.strip()]
    detail = complementary_text(title, ' '.join(
        line for line in paragraphs if line.rstrip('.!?') != title.rstrip('.!?')))
    if detail:
        lines.append(detail)
    return lines
