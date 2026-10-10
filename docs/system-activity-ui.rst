System in motion: fixed 2D evidence map
======================================

The existing dashboard exposes ``/market?tab=live``. No new scanner, worker,
schema, provider request, paid AI call or execution path is added. Only the
existing bounded research GET is used once per minute; the parent dashboard
refreshes every 30 seconds. Requests do not overlap, hidden pages pause polling
and unmount aborts requests. Failures preserve retained data with a warning.

Presentation
------------

The only primary view is an SVG 2D map with fixed coordinates and viewBox:
no camera, drag, orbit, zoom or horizontal pan. Selecting a stock does not
reframe it. Mobile uses two station columns and normal vertical scrolling.
There is no "Stations & stocks" switch. Summaries appear beneath the map on
phones and beside it on desktop. Full sample lists remain reachable through
"Sampled stock details". Search, scope, service status and full evidence are
disclosed on request; stale/invalid/capped-sample/session warnings stay visible.

The decorative spider uses an alpha, orthographic titanium CGI sprite rather
than drawn outlines. Eight clipped raster limbs articulate around their hips;
the body uses the same texture. The texture is bundled locally, not fetched
from X or an external image service. It does not require WebGL or a 3D camera.
It moves for 3.2 seconds only to newly observed evidence destinations, at most
four per batch. This is an illustration of received evidence, NOT live worker
tracking or successful-stage proof. Initial load, unchanged/stale/future data,
reconnection, paused/hidden states and reduced motion do not initiate/replay
travel. Hidden/paused batches are consumed. A separate decorative idle pose
adds subtle body breathing/sway and staggered leg settling, without changing
map coordinates, evidence timestamps, counters, status or stage membership.
It is labelled decorative, not worker activity. No random tour or
requestAnimationFrame renderer. Pause, hidden/unavailable state and reduced
motion disable both idle and travel animation; unchanged polls never replay
travel. Idle uses CSS transforms only, no extra polling or timers.
The active view imports no 3D module or Three.js; the frontend build emits no
3D activity chunk. Older unmounted sources and tests remain in the repository.

Evidence contract
-----------------

* Latest retained scan per ticker in a capped 24/48/168-hour sample, alongside
  retained signals and main positions; not exhaustive universe coverage.
* Candidates join by scan/ticker, signals by signal ID, positions by trade/
  signal ID, never ticker alone. Other scans are separate chains.
* Station membership comes from explicit evidence. Target PASS does not imply
  news/AI/execution PASS; missing stages remain unknown. Decorative webs,
  reactors and points are not additional observations.
* Allocation blocks are not quality rejects. Recovery uncertainty requires
  review; pending orders/signals are not fills. Shadow is excluded from the
  main map, not independent capital. Legacy missing results are unavailable.
* Existing weighted percentage/R results retain realized-net/open-gross and
  stale-mark distinctions. No cash, dollar P&L or invented return is shown.
* Stars are browser-only, capped at 100. No backend watchlist/trading mutation.
  Escaped React text, bidi isolation and keyboard controls are preserved.
* Graph caps at four records per cluster on phones, eight on desktop; omitted counts and full lists
  preserve access to all retained sample records. Source timestamps are shown.

Verification and preview
------------------------

Run from ``service/frontend``::

    npm run test:activity
    npm run test:research
    node test-signal-presentation.cjs
    npm run build
    node tests/preview-system-activity.mjs

The preview binds 127.0.0.1:4318, uses synthetic fixtures only and rejects
non-GET requests; it does not connect to Production/AI/Telegram.
``?event-test=synthetic`` emits one ALFA update on the second fixture poll;
unchanged later polls must not replay it. ``&motion-test=synthetic`` explicitly
labels a visual QA fixture overriding reduced motion ONLY in the synthetic
preview. The actual app always respects the user's preference. This is not
live E2E evidence. Former GPU fixture URLs remain test-only, with no GPU scene.

CI/Cloud Readiness run the model/render tests. No migration/config change is
needed. A UI revert does not alter decisions or positions. This task does not
authorise merge or Production deployment.

Sprite provenance
-----------------

``service/frontend/src/assets/evidence-spider-titanium-v1.png`` was generated
with the built-in imagegen tool, transparent-background generation mode.
Prompt: "Premium photoreal CGI cybernetic spider, orthographic top-down,
facing right, exactly eight separated slender articulated legs, brushed
black titanium/graphite, restrained emerald thorax status light, realistic
metal highlights and ambient occlusion, transparent alpha, no background,
text, web, panels, watermark, cartoon or vector outlines."
The X video was viewed as inspiration; this is an original generated asset,
not a copy or extraction from that video.
