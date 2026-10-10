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
Reactor counts represent retained records, not the entire universe or successful
stage transitions. The explanatory sheet retains freshness/sample limitations.

Interaction
-----------

* Three primary destinations: reactors, sampled stocks, more.
* Reactor -> stock list -> focused stock -> optional full retained journey.
* Details open in a viewport-bounded sheet, not somewhere further down the page.
* Back pops one sheet; dismiss restores focus. Escape, keyboard focus trapping,
  background inertness and Telegram's optional BackButton are supported.
* Small-height containers omit preview chips, not stations or records. Lists keep
  all filtered records accessible. Touch targets are at least 44 CSS pixels.
* The fixed 2D map cannot be dragged or rotated. The same spider artwork is
  smaller. Station movement is limited to newly observed changes, not arbitrary
  trips. Hidden/paused/unavailable updates are discarded, including navigation
  away and back; idle motion is explicitly described as decorative.
* Reduced-motion preferences are respected by default. A viewer may explicitly
  enable illustrative motion or disable it without affecting the application.

Verification
------------

``npm run build``, ``npm run test:activity``, ``npm run test:research`` and
``node test-signal-presentation.cjs`` cover the existing projections plus the
mobile shell and display-only SDK navigation. Fixtures contain synthetic data.
The development-only ``tests/miniapp-harness.html`` is not an entry in the
production build. It supports loading/empty/error/stale states, 360/390/430
widths, short-height layouts and controlled observed-update animation.

Browser interaction checks must supplement static rendering: station/stock/
journey/back, focus restoration, search, small viewport bounds, error distinction,
motion completion and navigation without replay. Actual Telegram Web launch is
checked after publication. Responsive rendering and Telegram Web do not prove
native Android/iOS keyboard or client behavior; those remain a bounded limitation.

The earlier dashboard timeout is not claimed to be repaired by this UI change.
An unavailable refresh is now shown succinctly; retained data is never presented
as a fresh successful update. Request cadence and source semantics are unchanged.

Release
-------

Use existing exact-SHA CI/readiness and the protected main/server-pull deployment
gate; no parallel deploy or schema bypass. Verify actual build/deployed SHA,
role leases, read-only accounting baseline, encrypted backup and retained previous
image after release. No test news, trades, AI calls or Telegram messages.
