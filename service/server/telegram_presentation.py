"""Plain-text bidi presentation at Telegram delivery boundaries only.

Use Unicode isolates, never visual string reversal or directional overrides.
Stored evidence, dedupe keys and routing are deliberately outside this module.
"""
import re

RLM = '\u200f'
LRI = '\u2066'
PDI = '\u2069'
# Only Bidi_Control: preserve emoji ZWJ, variation selectors and combining marks.
_CONTROLS = re.compile('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]')
_HEBREW = re.compile('[\u0590-\u05ff\ufb1d-\ufb4f]')
_TOKEN = r"(?:[($€£+−@]|(?<![\u0590-\u05ff])-)?[A-Za-z0-9][A-Za-z0-9_.,:'/’%+\-−–@#$€£()\[\]=?&~]*"
_LTR_RUN = re.compile(r'https?://[^\s<>\u0590-\u05ff]+|' + _TOKEN + r'(?:[ \t]+' + _TOKEN + r')*')


def utf16_length(text: str) -> int:
    return len(text.encode('utf-16-le')) // 2


def _line(text: str) -> str:
    if not _HEBREW.search(text):
        return text
    return RLM + _LTR_RUN.sub(lambda match: LRI + match[0] + PDI, text)


def _prefix(text: str, budget: int) -> str:
    """Never split a number, URL or isolate when clipping for the wire limit."""
    result = []
    used = 0
    atoms = re.finditer(LRI + '[^' + PDI + ']*' + PDI + '|' + _LTR_RUN.pattern + '|.', text, re.DOTALL)
    for match in atoms:
        atom = match[0]
        size = utf16_length(atom)
        if used + size > budget:
            break
        result.append(atom)
        used += size
    return ''.join(result)


def telegram_text(text: str, *, limit: int = 4096) -> str:
    """Idempotent RTL paragraphs with intact LTR numbers, tickers and URLs.

    Apply AFTER source cleanup and timestamp/footer insertion. If the existing
    message plus controls exceeds the wire budget, mark clipping explicitly and
    retain a short final paragraph (community link / Admin event timestamp).
    The UTF-16 budget is conservative for Bot API text and caption limits.
    """
    clean = _CONTROLS.sub('', text)
    rendered = '\n'.join(_line(line) for line in clean.split('\n'))
    if utf16_length(rendered) <= limit:
        return rendered
    body, separator, tail = rendered.rpartition('\n\n')
    if not separator:
        body, separator, tail = rendered.rpartition('\n')
    if separator and utf16_length(tail) <= min(512, limit // 2):
        suffix = '…' + separator + tail
        return _prefix(body, limit - utf16_length(suffix)) + suffix
    return _prefix(rendered, limit - 1) + '…'
