# Weekly earnings calendar

Dedicated Telegram topic: **דוחות השבוע הבא**. No effect on scanning or paper trades.

## Source and scope

The official Earnings Whispers account `/u/epswhispers` posts its weekly chart at
https://www.reddit.com/r/EarningsWhisper/ . The public Atom feed at
https://www.reddit.com/r/EarningsWhisper/new/.rss links the original image on
`i.redd.it`. Redistribution permission was confirmed by the project owner on
2026-09-25. Captions retain attribution and a direct link to the source post.

The script requires the official author, an exact next-Monday date in the title,
an allowed image host, a source-post link, and tickers actually in the post.
It forwards the original image, not an AI recreation. The caption lists leading
tickers; this is a selected calendar, **not every company reporting that week**.
Reporting dates may change. No LLM is used.

## Schedule and operation

GitHub Actions workflow **Weekly earnings calendar** runs on hosted Linux runners.
Friday UTC slots 15:07–20:07 cover both Israel time offsets; a local-time guard
permits only 18:00–22:59 Friday in Asia/Jerusalem. The first eligible attempt is
approximately 18:07, with hourly retries until 22:07 if needed. GitHub can delay
scheduled jobs; delivery at an exact minute is not guaranteed. Public-repository
schedules may be disabled after 60 days of repository inactivity.

Neither the Windows computer nor Codex nor the application backend is required.
This does **not** migrate the scanner, Ollama, or other news feeds to the cloud.
Manual workflow dispatch defaults to read-only preview. Setting preview=false
uses the normal Friday-only send path and the same persistent deduplication.

```powershell
# Preview: fetch and validate, no Telegram message
.\.venv\Scripts\python.exe scripts\weekly_earnings.py
# Actual publication: Friday only, Asia/Jerusalem
.\.venv\Scripts\python.exe scripts\weekly_earnings.py --send
```

Private ignored `.env` supplies `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`TELEGRAM_EARNINGS_THREAD_ID` and optional `TELEGRAM_COMMUNITY_URL`.
For hosted execution, repository Actions Secrets are
`EARNINGS_TELEGRAM_BOT_TOKEN`, `EARNINGS_TELEGRAM_CHAT_ID`,
`EARNINGS_TELEGRAM_THREAD_ID` and `EARNINGS_TELEGRAM_COMMUNITY_URL`.
The workflow maps them to the server environment; none are frontend variables.
The automatic job-scoped GitHub token writes non-secret delivery state.
Disable `weekly-earnings.yml` in GitHub Actions to stop weekly publication.

SQLite state in ignored `.runtime/weekly_earnings.sqlite` prevents multiple sends
for the same week, including after restart or concurrent calls. Keep this file
when migrating the installation. No production portfolio database is modified.

Cloud execution (`--send --github`) additionally stores week/status JSON in the
dedicated `earnings-state` branch. An atomic SHA-checked claim is written **before**
the Telegram request. Completed weeks are skipped before fetching the feed.
Concurrency is serialized in Actions. A crash or uncertain send retains the claim
and blocks blind retries. Do not delete this branch or manually run a separate
local scheduler: local-only sends cannot see cloud state. The already delivered
2026-09-28 week was migrated as sent, without republishing it.

When Telegram delivery times out, its outcome may be uncertain. Automatic
resending is deliberately blocked; inspect the topic before reconciling the
delivery record. Never delete state blindly. Explicit HTTP rejection permits a
later scheduled retry. Missing/changed source formats and missing current-week
images fail closed rather than forwarding old images. No guaranteed publication
time or source uptime is implied. Friday-only scheduling does not recover a
missed Friday on a later day.

## Verification

`python -m pytest service/server/tests/test_weekly_earnings.py -q`
uses mocked Telegram responses and temporary SQLite files. Covers source/date
validation, ticker deduplication, year boundaries, caption size, image-host
restriction, persistent single-send protection, uncertain delivery and rate-limit
recovery. It never sends test messages to the live group.
