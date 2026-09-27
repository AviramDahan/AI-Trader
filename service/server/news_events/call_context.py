from contextvars import ContextVar

# Metadata only; the existing ai_call_usage ledger remains the sole cost ledger.
CURRENT=ContextVar('canonical_news_call',default=None)
