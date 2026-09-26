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

Credits: `/api/v1/credits` total_credits minus total_usage is account-wide balance,
not the key's monthly allowance. Hourly reconciliation and each completion precheck
check it without an AI call. Alerts below $2/$1 dedupe persistently per purchased-credit
total; only a manual purchase starts a new credit cycle. No automatic top-up.

Forecast requires seven continuous measured days of hourly provider usage samples;
gaps over three hours or counter resets restart the measurement window. Until then
the report says “אין מספיק נתונים”. The historical unassigned expenditure is not
used to calculate daily burn. Forecast = actual month-to-date spend + measured burn
times remaining calendar days. Monthly reset starts a new observation window.
Remaining credits, monthly allowance and mutually exclusive task costs are shown
separately. Budget notifications dedupe per UTC month.
Zero balance or exhausted monthly allowance prevents completions before retries.
A provider HTTP 402 creates a persistent AI-only latch: a confirmed manual credit
purchase or new UTC month permits checking again. If the balance was unavailable
when latched, an operator must reconcile before clearing it (or await month reset).
No AI request is used to probe recovery. Monitor/TP/SL have no dependency on this.
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
