Telegram-first activity workspace
================================

Scope
-----

``market/?miniapp=1`` opens the same public, read-only activity model in a
dedicated display shell. No provider, scanner, news, trade, API, schema or
Telegram delivery policy changes. The ordinary website retains its navigation.
No new message or topic is required: the existing Mini App URL remains valid.

The shell renders the eight reactors immediately, including while data loads.
Unknown counts are ``—``; only a received empty sample may display zero.
Reactor counts represent distinct sampled stocks, not the entire universe or successful
stage transitions. The explanatory sheet retains freshness/sample limitations.

Interaction
-----------

* Three primary destinations: reactors, sampled stocks, more.
* Public visitors can search and inspect details, but cannot mark stocks for
  tracking. Favorites controls/filter and browser preference reads/writes are
  removed from both shells. The engine watchlist and trading remain unchanged.
* Reactor -> stock list -> focused stock -> optional full retained journey.
* Details open in a viewport-bounded sheet, not somewhere further down the page.
* Back pops one sheet; dismiss restores focus. Escape, keyboard focus trapping,
  background inertness and Telegram's optional BackButton are supported.
* Each card previews up to three distinct stock symbols plus a ``+N`` remainder,
  including in short-height containers. Symbols are display-only within the
  station button; its sheet keeps all filtered records accessible. Counts measure
  distinct ticker symbols per station. Touch targets are at least 44 CSS pixels.
* The fixed 2D map cannot be dragged or rotated. The decorative spider and its
  motion controls have been removed from both renderers.
* Prominent step badges 1–8 and seven directional arrows show a continuous
  serpentine sequence. In Hebrew the first step starts top-right; in English it
  starts top-left. DOM/tab order remains chronological. Counts are separately
  labeled stocks, never used as step numbers. Arrows describe pipeline order,
  not proof a sampled stock passed earlier stages.

Verification
------------

The stock sheet opens ``Explanation & evidence`` rather than claiming a complete
chain. A short status summary precedes retained entry/stop/target/gross RR and
weighted position outcomes (realized net versus open gross, percent/R only).
Only documented stages get expandable cards; unavailable stages and technical
IDs/codes are separate, initially closed disclosures. All evidence times use
Asia/Jerusalem. Entry-order validity is explicitly not position expiry. A
validated AI response means schema validation, not entry approval. Allocation
blocks do not become signal-quality failures; missing evidence is neither a
failed nor passed gate. Other same-ticker scans remain separate chains.

The evidence renderer is shared with the ordinary website, performs no network
requests and cannot refresh a scan or mutate public state. Existing API gaps
(selection explanation or per-signal order links) are labeled, never inferred.

``npm run build``, ``npm run test:activity``, ``npm run test:research`` and
``node test-signal-presentation.cjs`` cover the existing projections plus the
mobile shell and display-only SDK navigation. Fixtures contain synthetic data.
The development-only ``tests/miniapp-harness.html`` is not an entry in the
production build. It supports loading/empty/error/stale states, 360/390/430
widths, short-height layouts and synthetic observed updates.

Browser interaction checks must supplement static rendering: station/stock/
journey/back, focus restoration, search, small viewport bounds, error distinction,
step order in RTL/LTR and absence of the decorative spider. Telegram Web launch is
checked after publication. Responsive rendering and Telegram Web do not prove
native Android/iOS keyboard or client behavior; those remain a bounded limitation.

The earlier dashboard timeout is not claimed to be repaired by this UI change.
An unavailable refresh is now shown succinctly; retained data is never presented
as a fresh successful update. Request cadence and source semantics are unchanged.

Read concurrency follow-up
--------------------------

Live read-only probing showed a dashboard read taking 5.23 seconds also delayed
a concurrent health read by 5.03 seconds. The synchronous dashboard and cached
quote handlers now run in FastAPI's existing bounded thread pool, like the
research handler. Payloads, DB queries, polling intervals, errors and all write
routes are unchanged. This removes event-loop head-of-line blocking; it does not
promise zero network delay or make retained data fresh. The isolated ASGI test
holds each read open while health must respond, checks identical JSON, and
ensures a failed read remains an error without invoking trading writes.

Release
-------

Use existing exact-SHA CI/readiness and the protected main/server-pull deployment
gate; no parallel deploy or schema bypass. Verify actual build/deployed SHA,
role leases, read-only accounting baseline, encrypted backup and retained previous
image after release. No test news, trades, AI calls or Telegram messages.
