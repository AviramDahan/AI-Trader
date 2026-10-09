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
* Initial loading and unchanged polling do not trigger evidence glows. A short
  arrival glow marks changed retained data, not ongoing worker activity.
  The spider has been removed from both 3D and SVG, including its model, gait,
  motion path rendering and styles. There is no moving evidence cursor.
  Source-time, stale/future/invalid/reconnection guards remain unchanged.
  Latest received update metadata keeps its source timestamp and explicit
  omitted count. Paused/hidden batches are consumed rather than replayed.
  Decorative background points are not stocks. Wires mean current station
  membership, never unrecorded successful stages. All retained records remain
  available through the station view/lists; graph nodes cap at eight per cluster.
* Browser-only stars are stored under ``ai_trader_visual_follow`` (at most
  100 tickers). They never edit the backend watchlist, scan priorities or
  trading policy. Tickers/names are escaped React text with bidi isolation.
* The optional map is a real, lazily loaded Three.js/WebGL2 scene. Stations,
  silk and station nodes have actual depth; drag/pinch
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
  Rendering is on-demand, with finite camera navigation capped at 30 frames/sec,
  device pixel ratio 1.5 and 1.6 million backing-buffer pixels. Hidden and
  offscreen scenes cancel camera navigation. Unmount/context failure disposes GPU geometries/materials,
  controls, observers, listeners and renderer. Decorative particles and lines
  are aria-hidden, not additional stock/activity observations.


Verification and release
------------------------

Selecting a stock focuses its retained node (or its station when capped), with
a finite 450ms camera transition. This is navigation, not new activity: it does
not claim a worker transition. Reduced motion jumps
directly to the view; manual orbit cancels camera travel. A compact summary
shows the recorded state, reason, source timestamp and available levels beside
the map on desktop and underneath it on mobile. No fixed sheet obscures content.
Missing levels remain unavailable, not zero. Full evidence opens only on request;
selecting a node never jumps to the full journey. Search and service details
are collapsible, without removing retained records.
The mobile 3D map is 520px high, with larger ticker labels and state symbols
alongside words (colour is not the only signal). Closed does not imply profit
or successful execution. Actual received changes briefly highlight their
current station and display their original source time, not the render time.
All original stale/future/reconnection/duplicate guards remain unchanged.

The default is now an information-first vertical station view, on both phone
and desktop. Each of the eight station rows names its checks, counts retained
records (not unique tickers or successful passages) and previews up to three
stocks with explicit state words. Selection expands that station and puts the
stock summary and requested evidence inline beneath its record. Earlier stages
are never inferred to have passed. Allocation-blocked signals are labelled as
paper-allocation blocks, not quality rejection. The expanded list caps at eight
records, retains any selected record beyond that cap and offers all remaining
records explicitly. Browser-only stars and search/window/station filters are
unchanged. The separate "3D map" switch mounts the existing graph only on
request; the default station view has no canvas, GPU scene or overlapping
bottom sheet. Switching views does not fetch, create or replay any activity.

Phone readability uses one full-width ticker/state row per stock, 14--17px
primary text and 48px or larger primary touch targets. Collapsed station
headings omit check descriptions on phones; opening the station reveals them.
Scope, polling and progression explanations are disclosed on request, not
deleted. Capped-sample, unavailable/stale and outside-session notices remain
visible. Source timestamps have their own line, and mobile summary stats use
two columns with a full-width scan timestamp. No data selection, state mapping,
network polling, execution or update-marker guards are changed by this layout.

Run from ``service/frontend``::

    npm run test:activity
    npm run test:research
    node test-signal-presentation.cjs
    npm run build

For isolated visual QA only::

    node tests/preview-system-activity.mjs

The optional localhost-only ``?event-test=synthetic`` preview creates one
synthetic ALFA update and shortens only research polling to two seconds.
Subsequent responses retain that timestamp and must not produce a new update.
This is a fixture harness, not a provider, AI or trading call.

``?renderer-test=unavailable`` uses a preview-only mock constructor to exercise
the unsupported-GPU fallback. ``?renderer-test=context-loss`` adds a clearly
labelled fixture button that invokes the actual WebGL context-loss extension;
all nine synthetic records must remain available in 2D afterwards. Neither
test introduces a production flag or a new API endpoint.

The 3D bundle is separate from the main dashboard and loaded only when the
optional map is opened. The current frontend build reports a roughly 562 KB / 143 KB
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
