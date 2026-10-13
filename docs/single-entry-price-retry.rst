BUY/SINGLE: wait for a valid execution price
==========================================

This is an opt-in entry-execution contract, not a new target policy. A new
BUY/SINGLE order carrying ``single_entry_price_retry_v1`` may decline a price
and remain pending until its ORIGINAL expiry. A later completed, eligible bar
must independently pass the unchanged limit, structural stop, ATR, resistance,
completed-high, minimum 2R, account and exposure gates. Levels are never moved;
no preferred limit price is substituted for the calculated execution price.

Only dynamic price failures listed in ``entry_price_retry.PRICE_REASONS`` are
retryable. Unknown/malformed contracts, mismatched frozen signal/order levels
and other hard failures remain terminal. Missing eligible bars still produce
``recovery_uncertain``; they cannot be skipped to obtain a later fill. Restart
and repeated bars cannot duplicate entry or exit. Extended/incomplete bars do
not open positions. Existing exit handling, including stop-first ambiguity,
is unchanged.

Creation and retained state
--------------------------

``STOCK_SCANNER_ENTRY_PRICE_RETRY_ENABLED=false`` is the default. Creation also
requires a recognized BUY/SINGLE V2 or breakout plan AND the existing full-bar
entry contract. V1, SHORT, Legacy and previously stored orders retain their
original semantics, including terminal price rejection. In particular this
does not revive the invalid ULTA order.

Turning creation OFF does not cancel, convert or stop managing saved retry
orders or positions. The immutable order contract includes version, created
time, original expiry and target-policy version. The bounded latest price
observation contains reason, actual checked price, completed bar opening and
observation time. It is not a fill, not a guarantee, and must reproduce the
claimed price failure under the frozen plan.

The dashboard/research/Mini App receive only a validated derived wait object.
They distinguish qualified signal, pending order and active position, and
explain the actual blocker. The existing outbox emits at most one price-wait
notice per order; later entry/expiry keep existing transition deduplication.
No new Telegram topic, dispatcher or public test message is introduced.

Backup and rollback
-------------------

No database migration or schema change is required (schema 7 unchanged).
Recovery snapshot format **6** explicitly preserves retry contracts and latest
observations on the included order; positions also preserve the immutable
retry version. Formats 1..5 remain readable under their existing restrictions.
Only a format-6 capable reader may restore format 6; do not relabel it. Existing
coverage remains open Native/Legacy/Shadow positions and recovery holds, not
automatic recovery of all ordinary pending orders. Holds with no fill/trade
keep their parent signal and reservation, including after original expiry.

The previous production reader, 268afbcb742a9a4607ee04ae036d92441c07d59f,
does not understand this execution contract. It is NOT a safe binary rollback
after retry data exist (even though the database schema is unchanged). A
future release must first install this capable binary with creation OFF,
verify services/accounting/encrypted backup and retain its actual server image
as the compatible rollback target. Only then may separately authorized
activation enable creation. Returning to the capable image with creation OFF
continues saved orders, protective exits and format-6 backups on the current
database. No database rollback or manual status conversion is permitted.

Tests and limits
----------------

The isolated suite covers first valid fill, bad-then-good price, unchanged old
contracts, original expiry, missing bars/holds, weekends/holiday, invalid
contracts, incomplete/extended bars, account guards, stop-first ambiguity,
repeat/restart, read-only public projection and message deduplication.
PostgreSQL additionally uses real age encryption and clean-schema restore
with mixed V1, Legacy, Shadow, SHORT, retry position and retry hold. The
existing no-deployment image workflow runs separate full application
processes through creation-OFF preparation, activation, simulated failure,
compatible return/restart, old-reader refusal, encrypted restore and exits.
It runs on ``codex/single-entry-price-retry`` without publishing images.

Historical ULTA demonstrates a very narrow legal execution-price corridor,
not a proven missed fill: the actual rejected execution price was not retained.
Synthetic bad-then-good tests prove this contract's behavior, not profitability
or any promised future fill. No live quote fetch, AI call, scan, Telegram
message, trade, production configuration change or deployment is part of
these tests or the implementation authorization.

Local commands::

    python -m pytest service/server/tests/test_entry_price_retry.py service/server/tests/test_signal_research.py -q
    python -m pytest service/server/tests -q
    # TEST_POSTGRES_URL must name a disposable database; fixtures isolate schemas.
    python -m pytest service/server/tests_pg -q
    npm --prefix service/frontend run test:activity
    npm --prefix service/frontend run test:research
    npm --prefix service/frontend run build

CI and Cloud Readiness must pass on the final PR version. A skipped workflow
is not compatibility proof. Deployment and flag activation require separate
approval; this change is prepared for review only.
