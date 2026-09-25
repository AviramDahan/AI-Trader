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

A Codex thread heartbeat named **דוחות השבוע הבא לטלגרם** runs Fridays at 18:00
Israel time, with additional opportunities at 20:00 and 22:00 if needed. It runs
the command below against this local checkout. The Windows computer and Codex
must be running; GitHub Pages does not run this schedule. The automation is
local app configuration, not installed automatically by cloning this repository.

```powershell
# Preview: fetch and validate, no Telegram message
.\.venv\Scripts\python.exe scripts\weekly_earnings.py
# Actual publication: Friday only, Asia/Jerusalem
.\.venv\Scripts\python.exe scripts\weekly_earnings.py --send
```

Private ignored `.env` supplies `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`TELEGRAM_EARNINGS_THREAD_ID` and optional `TELEGRAM_COMMUNITY_URL`.
Disable the named automation in Codex to stop weekly publication.

SQLite state in ignored `.runtime/weekly_earnings.sqlite` prevents multiple sends
for the same week, including after restart or concurrent calls. Keep this file
when migrating the installation. No production portfolio database is modified.

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
