Company financial reports: separate destination and simpler copy
==============================================================

SEC structured financial notices (quarterly and annual) dispatch as ``company_report``
to the dedicated ``TELEGRAM_COMPANY_REPORTS_THREAD_ID``. Ownership notices
remain ``sec_intelligence`` in their existing topic. Corporate results arriving
through regular news, stock/personal alerts and canonical news also use the
dedicated reports topic at the shared send boundary. Publication eligibility,
membership, evidence/version/epoch, freshness and single-publisher rules remain.
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

News-source results routing
---------------------------

``news_report_routing`` identifies actual corporate financial-result content in
English/Hebrew. Original reviewed source text marks regular/canonical result
headings; the shared sender also handles older pending message bodies. The AI
interpretation alone never determines the category. Quarterly GDP/CPI/import/
export-price releases, nonfinancial trial/election results, calendar previews
and standalone analyst actions stay news. Classification selects a destination,
never eligibility, issuer identity, numeric claims or a trading decision.

News-derived notices retain their reviewed text, currencies, explicit source
expectations and existing rendering. They are not reconstructed as a structured
SEC comparison and do not acquire invented analyst estimates or USD conversion.

The saved original news type/key remains unchanged for publisher fences and
rollback compatibility. The effective send type becomes ``company_report``
after all normal dispatch revalidation. Missing reports-topic configuration fails
closed. Historical notices are not moved or replayed. A rollback to an older
sender restores its old news destination; retain the compatible sender to keep
this routing behavior. Outbox ``event_type`` identifies the original publisher
contract, not proof of the actual historical Telegram thread.

Under the existing sole Telegram role lease, claimed rows are processed by ID.
Exact source/version peers converging from multiple old topics are suppressed
after a known sent or ambiguous receipt. General canonical aliases reuse the
existing exact evidence/time destination keys across old topics; saved keys are
not rewritten. New evidence versions are preserved. This adds no fuzzy merge or
guarantee of remote exactly-once delivery; existing transport/recovery rules stay
authoritative. Peer lookups are bounded and overflow fails closed explicitly.

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
