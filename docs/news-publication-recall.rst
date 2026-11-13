Supplemental market news
========================

Canonical public market news may include low-materiality updates with topical
relevance >= 0.90. This applies only to market events without verified stock
tickers. Personal and company alerts still require medium/high materiality.
Scores are retained unchanged; this does not relabel routine news as important.

Runtime settings:

* ``STOCK_SCANNER_GENERAL_NEWS_LOW_MATERIALITY_ENABLED=true``
* ``STOCK_SCANNER_GENERAL_NEWS_LOW_MATERIALITY_MIN_RELEVANCE=0.90``

Setting enabled to false restores the medium/high-only market gate. The numeric
setting is bounded to 0.80..1.00. Evidence sufficiency, independent quality review,
topical relevance, freshness, source rights, deduplication and AI budgets still
apply. There is no replay or publication quota. Existing analyzed backlog is not
requeued by this change. Trading admission and signal-news eligibility are separate.
