# Private AI budget reports

Send `/budget` (or `/budget@<bot username>`) in **AI-Trader Admin**.
The cloud Telegram role polls every ~30 seconds. Public group commands, bot
messages, edited messages and commands older than one hour are ignored.
No model is called and no credits are purchased by this feature.

Reports are queued daily at **08:00, 12:00, 20:00, 23:00 Asia/Jerusalem**;
DST is automatic. PostgreSQL keys prevent the same scheduled slot or command
update being queued twice after a restart. An outage can be caught up within
the scheduled hour; missed earlier hours are not replayed in a burst.

Reports use the existing hourly OpenRouter reconciliation snapshot. They show
the actual data timestamp separately from the report creation timestamp and
warn if the data is over 75 minutes old. Monthly spend, monthly cap remaining,
account credits, task totals, repairs and unassigned discrepancy remain separate.
Forecasts still require at least seven days of continuous measurements.

The existing private `admin_alerts` outbox delivers reports with bounded retries.
An ambiguous network delivery is marked `delivery_unknown`, not blindly resent.
Neither the scheduler nor the command can fall back to the public chat.
All Telegram network work runs outside a database transaction and only in the
singleton Telegram role, independently of Position Monitor.

No new secret or schema migration is required. Existing server-only
`TELEGRAM_ADMIN_CHAT_ID` and `TELEGRAM_BOT_TOKEN` are used. The command receiver
owns Bot API `getUpdates`; do not add a second poller or webhook for this bot.
Polling failures back off, respect Retry-After, and preserve the saved offset;
the scheduler and outbound notifications keep operating independently.
