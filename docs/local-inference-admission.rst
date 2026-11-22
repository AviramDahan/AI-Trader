Local inference admission and scanner freshness
==============================================

The inference gateway has one native generation slot. Previously its legacy
``ready=false`` represented both a healthy occupied slot and a genuine outage.
With paid fallback disabled, a scanner candidate could therefore fail before
any model request even though another application's inference was progressing.
This is a reproduced code defect, not proof that every historical
``LocalUnavailable`` rejection had that cause.

The legacy ``ready`` field keeps its original meaning. New gateways additionally
publish content-free ``admission`` metadata with version1 and strict boolean
``available`` and ``busy`` fields. An active verified request remains available
while occupying the slot even if periodic metadata ages during that request.
Cold model residency does not prevent admission. Health remains read-only.
Unverified, stale idle, contradictory or incompatible metadata is unavailable;
an old gateway's false-ready response is not assumed to mean busy.

A concurrent completion is rejected before native inference with HTTP429 and
the exact body ``{"reason":"local_inference_busy"}``. The new cloud reader
classifies only that strict response as ``LocalBusy``. It neither starts a model
retry, activates paid fallback nor marks the transport outage cooldown. Other
429/503 responses remain failures. Old clients still fail closed. The gateway
does not enqueue requests, reserve memory, or increase native concurrency.

During the regular session the scanner can wait for confirmed busy capacity
using only bounded health GETs, after a candidate passes the initial structural
precheck. Waiting shares the existing120second
deterministic/refill allowance rather than giving the tail another allowance.
After waiting, the scanner acquires another fresh entry quote, repeats the
target/trigger checks and constructs the review rationale from those fresh
inputs. The original shortlist's news eligibility
is refreshed; tail rows retain their target-before-news ordering. Session and
durable emergency state are checked again, followed by all normal quote,
trigger, target, AI, news, risk, execution and post-AI admission controls.

Readiness is not a reservation. If the slot is occupied again at the final
request boundary, the scanner records a distinct deferred result and ends that
scan's selection safely. A no-generation deferral is not counted as an AI model
attempt, token usage, or a completed decision, and consumes no unused selection
quota. Actual previous model attempts remain counted. There is no retrospective
fill or replay of a deferred candidate. A later normal scan must rediscover and
revalidate it. This bounded wait improves access to a temporarily occupied slot;
it does not guarantee a free slot, an AI approval, a position or profitability.

Tests use synthetic providers, clocks, concurrent gateway threads and isolated
scanner fixtures. They cover strict availability and429 parsing, cold health,
single-generation concurrency, bounded/cancelled waiting, first valid review
after contention, no paid fallback/cooldown or fabricated attempts, and fresh
session/emergency/target checks. These are Offline/Mock proofs, not a live model
or regular-session trading result. Model identity, context/output limits, model
attempt budgets, quality checks and trading thresholds are unchanged.

Lossless review evidence layout
-------------------------------

The final-review payload previously repeated complete news records under
``candidate.news`` and their headlines under ``recent_news``. It also repeated
the same price zones under the candidate and its validated target plan. The
new projection moves complete news rows once into ``recent_news`` only when
their existing headline projection is exactly equal, and removes the candidate
zone copy only when it matches the retained plan zones. All original source
fields, excerpts, ordering, zones and pivot confirmation timestamps remain.
Different copies are preserved. An offline inverse proves exact restoration
of the previous logical payload; the frozen execution plan is never changed.
The system prompt explicitly names the retained evidence locations.

This reduces redundant serialization, not coverage or context/output budgets.
It does not prove every request will fit the unchanged context, nor that a
model will approve the same trade or perform profitably. Oversized requests
still fail closed; a live-model capacity result needs separate evidence.

Retained accounting audit
-------------------------

``scripts/trading_readonly_audit.py`` now separates native fill consistency,
cash consistency and cumulative fees/realized P&L. Active-only recovery omits
closed history while preserving cumulative account totals. Comparing those
totals directly with the retained trades previously produced a false mismatch.
With only the cash opening baseline, cumulative fees/P&L are explicitly
``NOT_VERIFIED / OPENING_HISTORY_GAP``.

The optional ``--opening-snapshot`` and ``--identity`` arguments read an existing
encrypted original in bounded memory only. The original checksum must match
the live import ID, primary account and cash baseline. Opening fees/P&L derive
from that exact original, never from a current residual. A valid original can
prove cumulative consistency, while a genuinely changed current total fails.
No account balances, fills or import formats are modified; no new backup is
created. Output contains statuses/counts and excludes financial amounts and
decrypted content. Full historical performance and a new live trading chain
remain separate evidence requirements.
