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
  The spider is a finite cursor sweep to a newly observed, timestamped evidence
  update. There is no continuous/idle animation. Only changed retained records
  with an advancing source timestamp within 150 seconds can trigger a sweep;
  newly exposed rows must also postdate the viewer baseline. Initial load,
  identical polling, invalid/future/old timestamps and reconnection establish
  or preserve a baseline instead of replaying work. Filter changes never create
  updates. A sweep visits at most four visible update destinations, never assumed
  intermediate stages, and reports omitted updates. A destination outside the
  eight-node graph cap points to its actual station, not a fabricated node.
  This is a cursor to data received by the view, NOT real-time worker processing
  or a reconstruction of unobserved transitions. Updates while motion is paused,
  hidden or unavailable are consumed, not replayed when viewing resumes.
  Each sweep stops within 3.2 seconds and honours reduced motion. Decorative
  background points do not represent additional stocks.
  Every selectable ticker node comes from retained evidence. Wires indicate
  current station membership, not unrecorded successful stages. The graph
  shows at most eight nodes per cluster, with an explicit omitted count and
  the remaining records available in the station lists.
* Browser-only stars are stored under ``ai_trader_visual_follow`` (at most
  100 tickers). They never edit the backend watchlist, scan priorities or
  trading policy. Tickers/names are escaped React text with bidi isolation.
* The default map is a real, lazily loaded Three.js/WebGL2 scene. Stations,
  silk and the eight-legged procedural spider have actual depth; drag/pinch
  orbit and zoom the camera. There is no auto-rotation, idle particle motion,
  model download, post-processing pipeline or external rendering service.
  Stock and station labels are projected HTML buttons, remaining upright,
  bidi-isolated and keyboard-operable. An explicit 2D toggle preserves the
  existing SVG. Unsupported WebGL2, context loss, renderer errors and lazy
  chunk/render failures fall back to that same interactive data view.
  Mobile station cards stack. Below 640px the graph uses a dedicated vertical,
  two-column station layout rather than a horizontally scrolling desktop map.
  Resizing resets cursor geometry without replaying consumed updates. Zoom is
  presentation-only and targets the selected station or map centre; Full map
  restores the complete view. The decorative field is deterministic, capped at
  640 vertices on desktop / 320 on mobile with at most three connections per
  vertex. These vertices are aria-hidden, non-interactive and never stock nodes.
  No timer animates them. 3D depth is presentation-only, not a ranking score.
  Rendering is on-demand, with finite cursor sweeps capped at 30 frames/sec,
  device pixel ratio 1.5 and 1.6 million backing-buffer pixels. Hidden and
  offscreen scenes cancel animation; resizing/remounting does not replay a
  consumed update. Unmount/context failure disposes GPU geometries/materials,
  controls, observers, listeners and renderer. Decorative particles and lines
  are aria-hidden, not additional stock/activity observations.

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
Combining it with ``&event-test=synthetic`` creates exactly one synthetic ALFA
fixture update and shortens only the preview's research polling to two seconds.
Subsequent responses keep that same event timestamp: they must not restart
the crawler. This is a localhost fixture harness, not a provider/AI/trading call.

``?renderer-test=unavailable`` uses a preview-only mock constructor to exercise
the unsupported-GPU fallback. ``?renderer-test=context-loss`` adds a clearly
labelled fixture button that invokes the actual WebGL context-loss extension;
all nine synthetic records must remain available in 2D afterwards. Neither
test introduces a production flag or a new API endpoint.

The 3D bundle is separate from the main dashboard and loaded only when this
view is opened. The current production build reports a roughly 575 KB / 146 KB
gzip 3D chunk and Vite's existing 500 KB chunk-size warning (not suppressed).
The remaining dashboard does not eagerly load Three.js. npm audit also reports
five pre-existing advisories in unchanged Vite/esbuild/router/source-map
dependencies; none is in Three.js or its newly introduced dependencies. No
unrelated dependency upgrades are included here.

This preview binds 127.0.0.1:4318, serves synthetic fixtures only and rejects
non-GET requests. It is not live connectivity or Production E2E proof. The
normal app uses existing public API data, not fixtures. CI and Cloud Readiness
run the new model/render tests; no live environment or trading settings need
changing. No migration is needed. A code revert removes the tab without
altering retained decisions, positions or browser watchlist data. This change
does not authorize merging or deploying the branch.
