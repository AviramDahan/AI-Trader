Entry-flow evidence and optional intraday triggers
================================================

Scope and unchanged policy
--------------------------

The dated 20 October investigation found missing same-clock relative-volume
evidence, daily-only triggers for the independent price routes, and insufficient
input provenance to explain every HOLD/invalid-history observation. It did not
prove an incorrect HOLD, bad RR calculation, profitable alternative, or vendor
cause for the old invalid OHLCV cohort. That original missing snapshot cannot be
reconstructed. No rounding tolerance, fabricated bar, lower RR/confidence,
positive-news assumption, model shopping, quota, or mandatory BUY is introduced.

The old Baseline, daily independent detectors, News/SEC, AI, risk/exposure,
single-target/full-bar entry, emergency pause, TP/SL and existing contracts retain
their semantics. PEAD is unchanged. No broker integration is added.

Default-off additions
---------------------

``STOCK_SCANNER_INTRADAY_RVOL_CONTEXT_ENABLED=false`` permits the existing
scanner's bounded Yahoo adapter to acquire comparable completed sessions only
when enabled. See ``intraday-volume-evidence.rst`` for the exact cumulative
definition, ten-session coverage, clocks, split/half-day handling and UNKNOWN
cases. Six distinct acquisition attempts per scan share the pre/post-review
budget. Cache-only evaluation after a fetch uses the actual later clock and
the original current-quote cutoff. Missing evidence is never numeric zero or a
new Baseline/daily hard gate; local acquisition is not a paid AI call.

``STOCK_SCANNER_INDEPENDENT_INTRADAY_ENABLED=false`` adds a separately versioned
prior-daily setup plus completed regular 5m/RVOL witness for VCP, Momentum Burst,
Pullback Reclaim and RS Leader. It is OR discovery, not another Baseline filter.
Provisional queue membership is explicitly not DETECTED, attribution, AI
approval, order or position. Confirmation precedes targets and AI. A valid old
daily/Baseline alternative survives failed optional confirmation. Existing global
shortlist/AI/signal quotas and rotating fair queues remain bounded.

The new RVOL thresholds are explicit untuned intraday hypotheses, not evidence
that the numerically similar daily ratios have the same meaning or expectancy.
The new detector/package/execution versions cannot be silently downgraded into
old v1 contracts. Levels, support, chase cap, source clocks and witness are frozen;
post-AI and actual fill guards validate them without regenerating levels. A
confirmed reclaim can retest only above its frozen EMA support; breakout paths
remain strictly above frozen pivots. The existing expiry/full-bar/retry policy
still applies; there is no claim of continuous trigger confirmation until fill.

New history receipts stamp their explicit Yahoo adjusted-price basis. Old cache
receipts without that stamp remain usable by unchanged old routes but UNKNOWN
for the optional new mode until a normal source refresh, not a forced fetch.

Private observation improvements
--------------------------------

``review_input`` is a separate idempotent ``status=observed`` journal stage. It
captures a strict bounded factual projection of the actual initial model user
payload before provider IO. Exact UTF-8 user-content and sanitized-projection
hashes have distinct scopes. Per-attempt logical-message hashes distinguish
repairs without storing prompts or pretending to hash provider HTTP wire bodies.
Model output, article bodies, authentication and arbitrary nested fields are not
copied. Text private-pattern filtering and explicit omissions/truncation remain
visible; this is partial evidence, not a complete replay or historical revision
archive. Optional capture/storage failure never authorizes or blocks trading.

Invalid daily OHLCV retains a typed fixed-predicate diagnostic: source/decision
clocks, first offending completed session, consumed-prefix count and SHA256.
Only the actual available prefix through the first failure contributes, not future
or unconsumed rows. Nonfinite cells have canonical diagnostic tokens, not repaired
prices. Raw offending values/frames are not exported. Old absent evidence stays
unknown; no historical attribution or explanation is invented.

Compatibility and release gate
-------------------------------

Any new intraday attribution (including mixed Baseline audit) or execution
requires active-state format10. Emergency history cannot mask it as format9.
New readers retain old formats/contracts; old readers must reject format10.
Bridge creation stays immutably disabled, while it must preserve pending/held
contract guards, reservations, open positions and exits on the same current DB.
Recovery still excludes ordinary pending orders/history: do not claim otherwise.

The currently deployed old image cannot satisfy the new format/version capability
gate even with creation flags OFF. The direct actual-old compatibility path is
preserved. A separately verified exact-candidate certificate may select a
supported immutable Bridge10 while preserving the actual old identity in the
journal; a stored tag/pin by itself is insufficient. Strict format10 managed
backup-proof support and a tested controlled forward/failure/rollback path are
required. See ``compatible-paper-deployment.rst`` for exact final-main artifacts,
target proof, serialized timer/helper handling and explicit paused-entry control.
No old-image compatibility is fabricated and no safeguard is skipped. This change is isolated;
engineering tests do not establish a natural trade or profitability. Paper
performance remains DATA_INSUFFICIENT until properly attributed net closed trades
exist; there is no promised entry count, win rate or return.
