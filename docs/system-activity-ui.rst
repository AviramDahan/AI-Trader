System in motion: read-only station view
=======================================

The existing dashboard now exposes ``/market?tab=live``. No new scanner,
worker, database schema, provider request, paid AI call or execution path is
introduced. New view code uses only GET requests to the existing bounded,
read-only ``/api/scanner/research`` endpoint. The parent dashboard already
refreshes its public snapshot every 30 seconds; research is refreshed once
per minute and uses the existing server-side 60-second coalescing cache.
Requests do not overlap, hidden pages pause research polling, and unmount
aborts the pending research request. Server failures preserve the last
snapshot, with an explicit warning instead of a live claim.

Evidence contract
-----------------

* The board shows the latest retained scan per ticker in the selected
  24/48/168-hour sample, plus retained signals and main positions. It is not
  exhaustive coverage of the universe, a full-history ledger, or an assertion
  that a stage is actively executing. Existing report limits are disclosed.
* Candidate identity is ``scan_id + ticker``. Signals join by signal ID;
  positions join by trade/signal ID, never merely by ticker. Other scans of
  the same ticker are labelled separate chains in the detail view.
* One current station is based on explicit retained evidence. Target PASS
  alone does not imply news, AI or execution PASS. Unrecorded stages stay
  unknown in the journey. A technical record does not assert every gate
  passed. A signal with an unlinked reported fill requires review; it does
  not become an active position.
* Allocation blocking is distinct from signal quality. Recovery uncertainty
  remains blocked/needs-review, not entered. Expiry is not a trading exit.
  Shadow is excluded from the main execution board and never independent
  capital. Legacy is labelled; incomplete outcome history is unavailable,
  not zero.
* Outcome percentages/R use the existing research calculations and their
  partial-position weights. Realized net is separate from open gross; stale
  completed-bar marks are labelled. No cash, dollar P&L, allocation amounts,
  account-return sum or new performance computation is displayed.
* Initial loading and unchanged polling do not trigger evidence glows. A short arrival glow
  reflects a changed retained revision, not an invented transfer or ongoing
  worker activity. It is suppressed after errors and for stale snapshots;
  reduced-motion users see no animation.
  The organic network also includes an explicitly labelled decorative spider:
  its continuous visual tour is NOT scanner execution, progress, or an actual
  trade transition. It traverses occupied clusters only, stops on errors,
  stale/missing data, hidden pages or the pause control, and honours reduced
  motion. Decorative background points do not represent additional stocks.
  Every selectable ticker node comes from retained evidence. Wires indicate
  current station membership, not unrecorded successful stages. The graph
  shows at most eight nodes per cluster, with an explicit omitted count and
  the remaining records available in the station lists.
* Browser-only stars are stored under ``ai_trader_visual_follow`` (at most
  100 tickers). They never edit the backend watchlist, scan priorities or
  trading policy. Tickers/names are escaped React text with bidi isolation.
* The interactive SVG is a group with keyboard-operable station buttons,
  not a single image that hides its controls from assistive technology.
  Mobile station cards stack, and only the network region scrolls horizontally
  to keep its labels readable.

Verification and release
------------------------

Run from ``service/frontend``::

    npm run test:activity
    npm run test:research
    node test-signal-presentation.cjs
    npm run build

For isolated visual QA only::

    node tests/preview-system-activity.mjs

The optional localhost-only ``?motion-test=synthetic`` preview applies a
fixture-only stylesheet for testing animation when the browser has reduced
motion enabled. Its banner explicitly identifies the forced synthetic test.
It never changes system preferences or production reduced-motion handling.

This preview binds 127.0.0.1:4318, serves synthetic fixtures only and rejects
non-GET requests. It is not live connectivity or Production E2E proof. The
normal app uses existing public API data, not fixtures. CI and Cloud Readiness
run the new model/render tests; no live environment or trading settings need
changing. No migration is needed. A code revert removes the tab without
altering retained decisions, positions or browser watchlist data. This change
does not authorize merging or deploying the branch.
