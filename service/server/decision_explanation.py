"""Bounded public projection of an existing model explanation, never a prompt."""
import re

MAX_CHARACTERS = 800
_PRIVATE = re.compile(
    r'https?://|postgres(?:ql)?://|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|'
    r'-----BEGIN .*PRIVATE KEY|(?:sk-or-v1-|sk-proj-|gh[pousr]_)[A-Za-z0-9_-]+|'
    r'\d{7,12}:[A-Za-z0-9_-]{25,}|Bearer\s+\S+|'
    r'(?:password|api[_ -]?key|access[_ -]?token)\s*[:=]', re.I)


def public_reason(value):
    if not isinstance(value, str):
        return None
    if _PRIVATE.search(value):
        return None
    text = re.sub(r'[\x00-\x1f\x7f\u061c\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]', ' ', value)
    text = re.sub(r'\s+', ' ', text).strip()[:MAX_CHARACTERS]
    return text or None
