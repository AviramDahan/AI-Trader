Signal path correctness and research evidence
============================================

Scope
-----
No changes to Technical scoring, target/RR policy, news-pipeline publication,
final-review thresholds/model, sizing, position lifecycle or accounting.
No historical observations are rewritten and no existing orders are replayed.

* Daily history is finalized using the time it was downloaded. Cached partial
  candles cannot become completed merely because the clock later passes close.
  Technicals, market context and target structure use the same completed input.
  The existing conservative 16:05 ET cutoff is retained. After a completed
  session, stale symbols are refreshed even before the 20-hour cache TTL.
  Cache format 2 records per-symbol observation times; format 1 is read using
  its recorded global observation time. Old software rejects format 2 and
  downloads a new disposable cache. No database migration is needed.
* The existing four-day history fallback remains unchanged; an unsuccessful
  provider refresh is not proof of new daily data. Older symbols retain their
  individual observation time even if a majority refresh succeeds.
* Extended-hours/last-known quotes are research-only. They have source/time,
  freshness and a false entry-eligibility flag. Waiting for the regular session
  is counted separately from quality rejection. No AI/order is initiated by
  this research path. The regular quote freshness gate is unchanged.
* Up to six deterministically eligible reviews are selected from the existing
  bounded shortlist, in its existing rank order. Pre-AI quote/target/cooldown
  failures do not consume a review slot. A genuine AI HOLD/failure does consume
  one; it is not replaced to bypass the six-review cap. The three-signal cap and
  existing global budget gate remain unchanged.
* Existing canonical company-news observations complement Yahoo. Public
  routing/publication is not required. This is a bounded read-only snapshot;
  no ingestion, enrichment, analysis or re-analysis is triggered. Verified
  company/primary subject, source rights, conflicts, URL and publication time
  are checked again. Backlog, withdrawn, unverified and opinion-only evidence
  cannot qualify. Signal-news age stays at its existing 72 hours; this does not
  change the separate public universe-news freshness policy. Exact source URLs
  are deduplicated and provenance retained. Yahoo failure is isolated; final
  stock AI review still decides whether evidence is relevant/sufficient.
* Final review receives the current eligible quote and validated target plan,
  with the daily reference close/time separately labeled. Post-review quote and
  target checks still run; nothing moves levels to rescue a failed setup.
* AI decision telemetry is allowlisted and durable in the existing journal,
  including separate HOLD/confidence/relevance failures and uncalibrated score.
  No prompt or free-text model rationale is added to research telemetry.
* Strategy-feed projection happens only after authoritative record_signal
  commits. Its frozen display payload stays in technical_json. API ownership,
  payload checks and a transaction/row lock link one public projection to one
  scanner signal. A bounded retry posts only that projection, never a new order,
  AI review or Telegram message. Recovery backups intentionally retain only
  their existing accounting/target-plan contract, not this display retry payload.
  No backup-format change is claimed.

Verification and release
------------------------
Synthetic provider mocks and isolated SQLite/PostgreSQL tests cover partial
cache provenance, calendar rollover, fail-closed news, bounded refill, closed
session, actual AI quote context, durable failure, concurrent publication and
decision idempotency. Frontend tests render the real research view without HTTP.
Full Linux CI/Readiness (backend, PostgreSQL, encrypted recovery, frontend and
container) must pass on the exact release code before the normal protected
deployment. Schema remains 6, backup contracts unchanged. The existing encrypted
pre-deploy backup and image-only rollback apply; no database rollback is needed.
After deployment verify actual image/build SHA, leases, accounting, backup,
monitor and natural observations. A closed market or no new qualifying signal
does not prove natural trading E2E; no test trade/AI/message is to be generated.
