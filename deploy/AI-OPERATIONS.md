# Private operations and AI costs

The existing Telegram worker runs deterministic accounting every hour and private
alert dispatch every 30 seconds. No LLM is used to calculate costs or alerts.
OpenRouter's existing Luna-only guardrail and the application use a $25 monthly
ceiling. Credit balance may run out earlier; automatic top-up remains disabled.

`ai_call_usage` records every attempted completion, including schema failures,
with task, model, tokens, reasoning tokens, provider `usage.cost`, latency and time.
Retries are an exclusive category; they are not double-counted as news/final spend.
Unavailable cost stays NULL. No historical task split is fabricated. Reconciliation
stores provider `usage_monthly`, `limit`, `limit_remaining`, and the unassigned
difference from the locally measured sum. A key-specific limit can be null even
when a separate assigned guardrail applies; do not interpret null as zero.

Forecast: provider month-to-date spend divided by elapsed calendar days, multiplied
by calendar-month length. Remaining days uses the same average, not a promise.
Sparse/partial-month operation makes this forecast unreliable; remaining credits
are separate from the monthly cap. Budget notifications dedupe per UTC month.
Health incidents dedupe until recovery and recurrence.

`TELEGRAM_ADMIN_CHAT_ID` lives only in protected server configuration and GitHub
Actions Secrets. Admin messages have their own persistent table, no public-chat
fallback, and bounded delivery retries. As with Bot API generally, a network loss
after delivery but before acknowledgement can still cause an ambiguous retry.
Do not promise exactly-once delivery under that failure.

The private GitHub health workflow checks API/database-backed portfolio health,
monitor, Telegram and hourly backup heartbeats every ten minutes independently of
the server. GitHub scheduling can be delayed. Its incident cache is best-effort
deduplication; cache eviction may cause a repeated outage alert. No secrets go in
artifacts, public variables, images or the frontend.

Market smoke runs at opening and throughout weekdays, without generating trades.
Saturday checks cannot establish live TP/SL or a successful trading day. Keep
Production provisional until live evidence is reviewed; never synthesize fills.

Recovery-State backups remain active-state only. Telemetry/admin history is not
included. After disaster recovery, reconcile provider spend before enabling AI;
re-establish private alert routing before sending operational messages.
