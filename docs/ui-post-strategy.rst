Post-strategy UI clarity and navigation
======================================

Scope
-----

Frontend-only changes based on the 20 October UI review. No trading policy,
API/DB contract, runtime configuration, deployment, news eligibility, AI quota,
cash, positions or Telegram delivery changes. This branch starts from main
70dcb2a and deliberately does not include PR90's price-news-context policy.
Preparing a PR is not authorization to merge or deploy it.

What changes
------------

* Early-skip telemetry with zero attempts no longer receives an AI-attempt
  heading. Unknown execution evidence remains unknown.
* Rejected target geometry is distinct from an execution plan. Candidate
  summaries do not show contradictory empty execution-plan fields or promote
  rejected RR into a plan ratio.
* Station counts have per-source knowledge. Missing research does not mean
  zero candidates; retained positions can still be visible.
* Forward Mini App sheets start at the top. Back restores scroll and focus,
  including when the original React DOM node has been recreated.
* News references use router-relative Links, preserving the Pages basename
  and Mini App mode. Current/history routing opens and focuses a linked
  record through collapsed details. Missing references are explained.
  Periodic reads do not repeatedly pull focus back to that record.
* Secondary Mini App pages retain primary navigation. Position rows show one
  status plus retained entry/stop/target, remaining portion and monitor time.
* Validated routes from the same retained candidate check are visible, without
  assigning old trades to new strategies. A shortcut opens route performance.
  Discovery is OR followed by shared gates; detection is not entry approval.
* Performance and outcome views share their time window. Coverage gaps,
  non-additive route membership and detector observations are explained
  without inventing unique-stock counts or historical AI. SINGLE/STAGED are
  exit policies, not new discovery strategies.
* Source diagnostics and watchlist settings are collapsed. The first 30
  matching news items are mounted initially, with increments of 30. Filters
  apply to all loaded records and reset this display limit. Sources and
  publication policy are unchanged.
* Research/performance use the existing bounded single-flight read poller,
  hidden-tab cancellation and foreground recovery. Missing scalar metrics
  are not NaN or zero, and missing allocation is not labelled Shadow.

Verification
------------

From service/frontend::

    npm ci
    npm run test:activity
    npm run test:research
    node test-signal-presentation.cjs
    npm run build -- --base /AI-Trader/

The new UI regression test first failed on the zero-attempt AI heading before
the fix. It covers that failure, rejected-plan separation, unknown/empty/future
timestamps, basename-aware links and nested-history reveal. Existing station,
entry, research, private Admin/auth and agent-office rendering suites remain.

Interactive isolated preview::

    npm run dev -- --config tests/ui-preview.config.mts

Open http://127.0.0.1:4334/tests/ui-post-strategy-harness.html.
Real scanner/Mini App components render synthetic records. Application fetches
are stubbed; unknown requests fail. The preview config does not inherit the
ordinary localhost API proxy. Charts receive a labelled synthetic SVG; no
market data is requested. Fixtures are not Production build entries.

Check phone widths, forward/back/Escape/focus, open/closed record references,
missing records, pagination/filter reset, shared windows and retained-data
failure. Responsive fixtures are not native Telegram or trading E2E proof.

Remaining work
--------------

This patch does not establish why an earlier network read failed or remove
the server's large research payload. Separate bounded read-model profiling
and projection are required before claiming the latency problem is fixed.

The private control-room endpoint does not expose effective emergency-entry
state in its current allowlisted response. This patch does not invent it from
component health or discovery flags. Adding an authenticated read-only
projection and testing it is a follow-up. Discovery off must not be labelled
as pausing pending entry execution; entry pause must not imply stopped exits.
