Telegram stock-news destinations
================================

This optional presentation change uses retained reviewed stock analysis only.
It does not call AI, infer sentiment from text, change publication thresholds,
add a delivery, or alter trading, budgets or publisher modes.

Configuration
-------------

``TELEGRAM_DIRECTIONAL_STOCK_NEWS_ENABLED`` defaults to ``false``. With it off,
the existing stock-news destination and all saved durable event types/keys
remain unchanged. With it on, ``stock_news`` routes to:

* ``TELEGRAM_POSITIVE_STOCK_NEWS_THREAD_ID`` for validated positive stock analysis.
* ``TELEGRAM_NEGATIVE_STOCK_NEWS_THREAD_ID`` for validated negative stock analysis.
* ``TELEGRAM_MARKET_NEWS_THREAD_ID`` (then ``TELEGRAM_NEWS_THREAD_ID``) for mixed,
  neutral, absent, invalid, unverified or non-current analysis.

Missing configured destination fails closed; it never spills to an unrelated
topic or implicitly creates one. A safe operator cutover maps the former
``TELEGRAM_STOCK_NEWS_THREAD_ID`` to General before enabling the flag. Thus an
OFF rollback or old binary sends future general stock news to General rather
than an archived topic. No history is deleted, replayed or rewritten.

Evidence and durable dispatch
-----------------------------

The original ``stock_news`` event type and outbox dedupe key remain intact.
Publisher fencing, subscription checks, source rights, freshness, report
classification and report duplicate guards precede the final destination hint.
Company reports override the directional hint. Personal/watchlist news, SEC,
Trump, signals and trade actions retain their established routes. A verified
multi-company event may retain its existing personal and broad audiences for
different ticker subsets; this change introduces no additional audience.

Legacy stock keys must match ``stock-news:<id>:<version>:<sorted tickers>``.
The reviewed row must be analyzed, not duplicated or errored, quality version
2 or 3, and all selected tickers verified. ``news_publication_audit`` version
is authoritative when present, including enriched evidence whose version
differs from the source row hash. Otherwise exact source hash (or explicit v1)
is required. Pending, failed and translation-only results have no direction.

Canonical evidence must match the current epoch, exact linked event/version,
an analyzed event with no rejection reason, and a completed analysis of that
same version. Verified identities must match event tickers. Canonical quality
validation is retained in the completed-analysis lifecycle, not a synthetic
legacy quality-version field. Both paths require a finite numeric relevance
within 0..1, medium/high materiality and an explicit positive/negative result.

Canonical general-story keys encode the actual physical destination using the
same retained result at queue and send. Existing prepared keys are preserved:
an evidence/configuration/destination mismatch cancels delivery rather than
rewriting the key or replaying a sent/ambiguous publication. Existing outbox
restart, lease, HTTP failure and unknown-delivery rules remain authoritative.

Verification
------------

``tests/test_directional_news_routing.py`` uses synthetic evidence, disposable
SQLite, the real canonical queue/send path and mocked Telegram HTTP. External
HTTP and the canonical analyzer are explicitly forbidden. It covers direction,
invalid/stale/unverified provenance, report priority, OFF compatibility,
publisher fencing, missing-target failure, destination identity, restart/no
resend, and preservation of distinct personal/broad ticker subsets. These are
offline behavioral results; they are not proof of live publication or content
quality, which requires a natural post after the operator cutover.
