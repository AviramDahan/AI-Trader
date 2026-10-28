Company financial reports: separate destination and simpler copy
==============================================================

SEC structured financial notices (quarterly and annual) dispatch as ``company_report``
to the dedicated ``TELEGRAM_COMPANY_REPORTS_THREAD_ID``. Ownership notices
remain ``sec_intelligence`` in their existing topic. Canonical company news,
guidance headlines and market news retain their existing publication rules.
This change does not generate a full earnings release or analyst-consensus
comparison where the structured source supplies neither.

The same verified material comparisons, dates, issuer validation, publication
cutover, freshness, paper-mode and kill controls remain authoritative. No AI call
is added. Identical comparison periods appear once, above the metric blocks;
mixed periods stay attached to their metric. Stored amounts remain exact. Public
USD amounts use Hebrew thousand/million/billion units, with up to two scaled
decimal places and ``כ־`` whenever scaling rounds the amount. Small unscaled
amounts, signed losses, percent and percentage-point units remain distinct.
Fiscal quarter numbers, EPS, consensus, causes and price reactions are not guessed.
No source link is shown. Existing source facts remain stored.

``ציפיות האנליסטים`` and ``התוצאות בפועל`` are separate sections. The existing
SEC comparison producer has no verified analyst-consensus feed, so expectations
are explicitly ``לא זמין``. Previous-year reported values never become analyst
estimates. No EPS, beat/miss or surprise percentage is fabricated and no consensus
provider, subscription, AI call or new trading input is added by this format change.

The durable ``sec_intelligence`` event type and accession dedupe key are unchanged
for recovery/rollback compatibility. Old pending SEC financial notices are
classified from their retained filing evidence at dispatch and routed to the new
topic in memory, preserving the original outbox row. Sent notices are not moved,
deleted or resent. A missing destination fails closed, never falls back to SEC
or General. SEC-derived company reports keep the SEC kill/mode dispatch check.

Provision ``scripts/configure_company_reports_topic.py`` inside the existing
configured Telegram service. It validates the forum and bot permission, sends
no notice, and keeps a private durable creation marker. An ambiguous creation
requires operator inspection; rerunning cannot create another topic. Configure
the returned private thread ID in the host's protected runtime.env as part of
the separately approved release, then verify the effective scanner/Telegram
setting. Do not use the original checkout's .env or restart a role alone.

No schema or trading-contract change is needed. An older binary still understands
the saved outbox events and SEC safety controls; its historical destination is
the SEC topic, not the new company topic. It never interprets the new display
category as an unknown trading event. Do not replay pending/failed notices to
manufacture delivery proof. Natural delivery is separately verified when a new
eligible filing arrives.
