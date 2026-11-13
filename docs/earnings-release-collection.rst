Independent earnings-release collection
======================================

Purpose and defaults
--------------------

Verified release facts are needed before PEAD data coverage can be accepted.
Previously the original-release producer returned OFF whenever PEAD discovery
was OFF, preventing natural coverage observation through that producer without
also enabling its trading route. The producer already exists; this change
separates its activation from trading rather than replacing the parser or
claiming a new data source.

``STOCK_SCANNER_PEAD_RELEASE_COLLECTION_ENABLED=false`` is an optional,
default-OFF data collection switch in the existing news feed worker. It does
not appear in discovery strategy flags and does not authorize PEAD admission.

.. list-table:: Independent switches
   :header-rows: 1

   * - PEAD strategy
     - Collection only
     - Producer permitted
     - PEAD route enabled
   * - OFF
     - OFF
     - No
     - No
   * - OFF
     - ON
     - Yes
     - No
   * - ON
     - OFF
     - Yes (unchanged)
     - Yes (unchanged)
   * - ON
     - ON
     - Yes
     - Yes

All permitted cases still require the immutable candidate capability and the
existing enabled, rights-approved canonical provider allowlist. An immutable
Bridge still returns OFF before catalog, database or network access, even if
both switches are set. Explicit injected ``enabled=False`` remains a hard OFF;
explicit ``enabled=True`` retains its prior test/caller behavior without
removing the Bridge or provider guards.

What collection actually does
-----------------------------

No new process, scheduler, schema, provider, credentials, LLM task or Telegram
delivery is added. The existing bounded producer can read retained canonical
source hints, verify original release pages, and append analytical facts and
recoverable job/checkpoint metadata. Enabling it is therefore NOT read-only:
it permits up to two original-page acquisition attempts per feed cycle and the
existing analytical database writes. Provider transport may fail or lack
rights/access; a flag does not establish a subscription, access or coverage.

The initial checkpoint can encounter up to 90 days of retained hints, examined
in batches of 200. Old releases may be processed first. Their actual later
availability and backfill marking must not become historical point-in-time
evidence, and no immediate coverage or trade count is promised.

Original page identity, issuer mapping, timezone-aware release publication,
actual availability, revisions, withdrawals, correction uncertainty, bounded
leases, fencing, retries, queue limits and provider circuits are unchanged.
Headlines, earnings calendars, SEC acceptance and fetch times are not release
publication substitutes. Same-URL revisions remain the supported correction
scope; unknown cross-URL relationships are not invented.

Observing and stopping
----------------------

Use retained ``pead_release_coverage_v1``, cursor/job metadata and the bounded
``earnings_release`` journal to distinguish acquisition, verified facts, unknown
reasons, backfill and unavailable coverage. A retained verified flag is not by
itself an independently validated universe-coverage or profitability claim.

Keep ``STOCK_SCANNER_PEAD_ENABLED=false`` during any separately approved
collection-only observation. Collection OFF is not an emergency entry stop:
PEAD ON retains its previous producer behavior, and saved entry contracts are
not canceled by either discovery/collection flag. The existing durable entry
emergency control remains the separate way to stop new and pending entries
while preserving position management and exits.

This change neither rewrites old facts nor alters active-position recovery,
holds, balances, execution, AI, News, RR, sizing, exposure or TP/SL. Active-state
backups do not suddenly cover this analytical release journal, ordinary pending
orders or omitted historical trades. PEAD activation and real source coverage
still require their own evidence and authorization; local tests are not that
evidence. Existing price routes, RVOL context and independent intraday switches
are unaffected.
