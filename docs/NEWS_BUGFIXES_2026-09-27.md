# News correctness fixes — 2026-09-27

- A refresh of the same headline/URL without an excerpt preserves previously
  collected source text, its content hash and analysis. Restoring that same
  excerpt does not trigger another analysis. Changed headlines and nonempty
  corrections still trigger analysis, including shorter corrected excerpts.
- A six-hour review propagates reported AI analysis errors instead of recording
  `no_new`/success. The prior success checkpoint is retained; the existing
  15-minute failure retry schedule is used. Terminal news-quality jobs are not
  requeued by this change. Successful later reviews clear the error.
- News alert counts now reflect actual outbox inserts. Cutover-boundary blocks
  and existing dedupe keys return false, not a reported successful enqueue.
  Enqueued does not mean delivered: delivery remains tracked by outbox status.

No model, trading threshold, news-materiality threshold, TP/SL, accounting,
candidate limit or historical data is changed. No migration or replay is needed.
This release does not implement news-provider enrichment, cheaper models or an
earlier age gate. Those are separate quality/cost changes, not these bug fixes.

Regression tests in `service/server/tests/test_news_pipeline.py` are also
inherited by the PostgreSQL suite. They cover content preservation, terminal
quality preservation, genuine corrections, accurate counts, all news routes,
AI failure/recovery and unchanged position quantities/stops. All external calls
are mocked; no test news or messages belong in production.
