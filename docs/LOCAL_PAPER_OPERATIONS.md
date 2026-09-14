# Autonomous US-stock paper scanner

The scanner keeps the upstream React/FastAPI/SQLite architecture and stable `us-stock-scanner` identity.
`/market` is its public dashboard; no user or ticker selection is required. There is no broker integration,
leverage, short selling, or real-money execution.

## Universe, schedule, and data

The default universe is the de-duplicated union of the S&P 500 and Nasdaq-100. S&P constituents/company
names come from Wikipedia; Nasdaq-100 membership and market-cap fields come from Nasdaq's public API. The
universe cache refreshes daily. Six months of adjusted daily OHLCV from Yahoo Finance/yfinance is cached
locally and normally refreshes once per 20 hours, rather than on every 30-minute scan. A rate-limited or
incomplete refresh uses only a sufficiently fresh cache; otherwise the scan fails closed.

Every cycle applies quantitative price-action, EMA20/EMA50, RSI(14), MACD, ATR(14), realized-volatility,
volume, liquidity, and 20-day range/return filters to the full universe. It then fetches exact-ticker company
news for a 25-name shortlist, ranks technical strength + news relevance + deterministic sentiment + SPY/QQQ
context, and sends only the best six candidates to local Ollama. Defaults are configurable in `.env`.

The dashboard reports actual counts for universe, usable data, technical candidates, news shortlist, Ollama
reviews, and approved signals. Zero approved signals is valid. A signal requires an intraday quote newer than
12 minutes; weekends, regular-hours closure, and shared NYSE/Nasdaq full-day holidays are reported separately.
Yahoo is a free unofficial delayed/no-SLA source, and the UI states this limitation.

## Signal and paper lifecycle

Each strong signal stores ticker/company, BUY/SELL/HOLD, planned/actual entry, original/current stop,
TP1/TP2/TP3, allocation and R/R per target, weighted R/R, model score and inputs, horizon/expiry, English and
Hebrew explanations, exact-source news, timestamps, and status. The model score is explicitly uncalibrated,
not a probability. Ollama text never controls prices, quantities, targets, cash, or order state.

Signal creation is not execution. BUY creates an expiring paper LIMIT order. A complete five-minute bar must
reach entry before a trade/fill is created. SELL closes a linked open long when its limit executes; without a
long it remains bearish-only and never creates a short. HOLD is not an order. Duplicate tickers, insufficient
cash, and configurable per-symbol/total exposure limits are blocked before order creation.

Paper cash, fills, original/remaining quantity, fees, slippage, realized/unrealized P/L, price cursor, settings
snapshot, and signal/order/trade/news links are stored in the database. Each event has a unique key and is
atomic, so reprocessing cannot duplicate a fill. Open trades are not truncated. Legacy JSON tracking data is
preserved as unverified and excluded from verified performance.

## Exit strategies and conservative bars

`single` remains the operational default for new trades. The same entry, initial risk, and bars are also
evaluated as an isolated `staged` shadow; shadow results do not affect cash or Telegram. An admin can explicitly
select the strategy for future trades in Results. Every trade has a settings snapshot, so changes never alter it.

The staged long freezes `R = actual entry - original stop`: TP1 closes one third at 1R and advances the stop to
entry starting with the next bar; TP2 closes one third at 2R and normally keeps the stop at entry (or advances
to TP1 when configured); TP3 closes the rounded remainder at 3R. Original R never changes, percentages total
100%, and the stop never moves away. Equal thirds yield 2R before costs—not 3R. Entry-price stop and breakeven
after costs are separate.

The price monitor is independent from scanning/Ollama. It processes complete five-minute bars after the stored
cursor and backfills within Yahoo retention. Gap opens fill conservatively. If a bar touches both the stop active
at its open and the next target, stop wins. A newly advanced stop never applies retroactively to that bar. A gap
beyond intraday retention reports an error. WIN/LOSS/BREAKEVEN is set only when the whole trade closes, using
cumulative net P/L and the configured threshold; TP1 alone is not a win.

Results compare single/staged trade count and period, marked net P/L, expectancy in R, win rate, drawdown including
open marks, target-hit rates, and breakevens. Under 30 closed trades shows a sample warning; there is no synthetic
history or superiority claim.

## News and six-hour open-position review

News is database-backed and newest-first. It separates broad market, scanner-shortlist, and open-position items,
with ticker/time/sentiment filters, source time/link, analyzed fields, and documented links. It states actual
coverage and never calls a shortlist a full-universe feed. Cached translation/analysis runs in the worker.

At entry, each open ticker is immediately due. Successful checks recur every six hours—including nights,
weekends, and holidays—while primary quantity remains. Trades sharing a ticker reuse one fetch/analysis. A
two-hour overlap catches late items; exact ticker metadata plus URL/title fingerprints prevent wrong links and
duplicate alerts. Ollama returns structured related/impact/materiality/thesis-effect fields and a concise Hebrew
explanation with uncertainty. Facts remain separate from interpretation. News may alert, but cannot close a trade
or change TP/SL. Provider/Ollama failure is an error, never “no news”.

## Telegram and health

Telegram uses a persistent server-side outbox with dedupe and retry/backoff. Hebrew alerts cover strong signals,
entry, every TP, stop changes, stop/final exits, and material position news. Partial exits include closed/remaining
quantity. Missing/disabled credentials safely disable delivery and never stop scanning. Tests mock delivery and
never send a live experimental alert. Secrets remain only in ignored `.env` and the private local backup.

Scanner status reports separate last attempt/success for prices, news, Ollama, scan, price monitor, position-news,
and Telegram. It distinguishes market closed, no signals, no new news, and errors.

## Start, stop, and verify

```powershell
.\scripts\start-ai-trader.ps1
.\scripts\stop-ai-trader.ps1
```

The Windows backend, worker, Ollama, and HTTPS tunnel must run; GitHub Pages is only the frontend. The scheduled
task/supervisor recover processes and republish Pages runtime config when the free tunnel rotates. The computer
must remain awake, logged in, and online.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest service/server/tests -q
npm --prefix service/frontend run build
.\.venv\Scripts\python.exe scripts/verify_end_to_end.py
.\.venv\Scripts\python.exe scripts/verify_browser.py
```

Live verification accepts zero signals and never injects production data. Limits remain free-provider delays/rate
limits, headline-only news, Ollama availability, five-minute OHLC ordering, and computer/tunnel uptime. This is
experimental paper trading, not investment advice.
