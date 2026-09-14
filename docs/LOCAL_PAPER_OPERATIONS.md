# Autonomous US-stock paper scanner

This keeps the upstream React/FastAPI/SQLite architecture. A local, non-admin scanner calls the
original `/api/signals/realtime` endpoint, so strong signals are visible in the original Market /
Trading Signals cards and their virtual positions are tracked by the original Positions and PnL UI.
No broker SDK, broker credential, real order route, leverage, or real-money mode is configured.

## Universe and schedule

The default universe is the union of current S&P 500 and Nasdaq-100 constituents. Constituents are
discovered automatically; users never enter tickers. S&P 500 membership/company names come from the
Wikipedia constituent table and Nasdaq-100 membership/market-cap fields from Nasdaq's public API.
The list is refreshed at most once per day and a seven-day local fallback is allowed only if a source is temporarily
unavailable. Within this large-cap universe, average 20-session dollar volume determines priority.

The scanner starts 20 seconds after the backend and runs every 30 minutes by default. `STOCK_SCANNER_SCAN_INTERVAL`
is configurable from 900 seconds upward. Six months of adjusted daily OHLCV is held in a local compressed cache.
The complete universe is refreshed at most once per 20 hours by default; ordinary scans reuse it and fetch only
shortlist news and fresh quotes. Missing constituents are fetched incrementally only if cache coverage falls below
95%; otherwise they wait for the next daily refresh. An incomplete/rate-limited
Yahoo refresh uses a sufficiently recent cache or stops without publishing. It never generates a weak fallback.
The scanner publishes at most three signals per scan. Outside US cash-market hours it may complete the
daily/news/AI review, but it cannot publish or open a position without a current intraday quote.

## Data, news, and analysis

- Adjusted daily and one-minute intraday OHLCV: Yahoo Finance through `yfinance` (free, no key, unofficial API).
- Recent company news: Yahoo Finance search feed, accepted only when `relatedTickers` contains the exact ticker.
  Headlines preserve publisher, link, and provider timestamp. The scanner uses titles/metadata only.
- Basic market context: SPY and QQQ 20/50-day trend plus 20-session return from the same daily feed.
- AI review: local Ollama model from `OLLAMA_MODEL`; headlines are explicitly treated as untrusted data.
  Ollama assesses direction agreement, news sentiment/relevance, confidence, and horizon. It cannot select
  tickers, URLs, order size, or bypass deterministic filters.

The deterministic stage first forms a 20–30 name liquid technical shortlist. News is fetched for the whole
shortlist, not just the AI inputs. Candidates are ranked by technical strength (50%), news relevance (20%),
direction-aligned headline sentiment (15%), and SPY/QQQ market alignment (15%). Only the top six go to Ollama
by default. The news cache is short-lived (15 minutes) and is never accepted beyond the configured freshness rule.

For each symbol the deterministic stage calculates price action, 20-day return, EMA20/EMA50, RSI(14),
MACD(12,26,9) histogram, ATR(14), annualized 20-session realized volatility, 20-session high/low, volume
ratio, and average dollar volume. Daily data older than four calendar days, missing context, missing/recently
irrelevant news, or an intraday quote older than 12 minutes fails closed and produces no signal.

## Strong-signal and paper rules

Default filters (all configurable in the ignored `.env`):

- average dollar volume >= $50M;
- ATR between 1% and 8% of price;
- technical agreement score >= 5 of 7;
- Ollama confidence >= 80% and news relevance >= 60%;
- news sentiment may not conflict with direction;
- calculated risk/reward >= 2.0;
- 24-hour same-ticker/same-direction duplicate cooldown;
- 25 technical/news candidates, maximum six AI candidates, and three published signals per scan.

BUY requires the bullish trend/momentum pattern; SELL requires the bearish mirror. HOLD or any rejected
candidate is retained in scanner status but is not published as a trade. A published SELL closes an existing
long paper position; without an existing long it is posted as a signal-only strategy and cannot create or increase
a short. An old opposing short from an earlier deployment prevents a new BUY until reconciled.

Entry is a one-minute quote no older than 12 minutes. Stop distance is the greater of 1.5 x ATR(14) and 1%
of entry. For BUY, stop is below entry and target above; SELL is mirrored. Take Profit equals entry plus/minus
stop distance x `STOCK_SCANNER_MIN_RISK_REWARD`. Rounded levels are rechecked against the minimum ratio.
Each BUY paper operation defaults to $100 notional, max $250 per symbol and $1,000 total scanner exposure.
The backend independently resolves the execution quote; the card's normal Price field is the recorded price.
Ambiguous execution timeouts set a reconciliation lock and are never retried automatically.

Every published signal is tracked locally from Entry. A separate five-minute monitor uses a fresh one-minute
quote to detect TP or SL, records `WIN`/`LOSS`, hit time, and hit price, and displays the result in the existing
scanner activity panel. These are observational paper levels: the monitor never submits a broker order or
automatically closes a paper position.

Telegram alerts are optional and off by default. Set `STOCK_SCANNER_TELEGRAM_ENABLED=true` plus the secret
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the ignored local `.env`. New-signal alerts include the complete
signal. `STOCK_SCANNER_TELEGRAM_ENTRY_ALERTS` controls a separate Entry notification and
`STOCK_SCANNER_TELEGRAM_LEVEL_ALERTS` controls TP/SL notifications. Missing credentials disable delivery safely.

Every published card contains: Ticker, Company, BUY/SELL, Entry, Take Profit, Stop Loss, Risk/Reward,
Confidence, Time Horizon, Reason, Relevant News, and UTC Timestamp. The expandable scanner panel shows
universe/data/candidate counts, recent AI reviews, rejected scans, last signal, last/next scan, and errors.

## Configuration

The documented keys live in `.env.example`. Secrets remain only in ignored `.env`, local SQLite, and
`PRIVATE_SETUP_CREDENTIALS.txt` plus its DPAPI-encrypted backup. `STOCK_SCANNER_TOKEN` is never returned by
the public runtime endpoint or bundled into GitHub Pages. Only public `BACKEND_URL` is a GitHub variable.

## Start, stop, and verification

```powershell
.\scripts\start-ai-trader.ps1
.\scripts\stop-ai-trader.ps1
```

The per-user `AI-Trader-Paper` Windows task starts at login and checks once per minute. An explicit stop marker
is respected until manual start clears it. The local supervisor recovers the backend, Ollama, and anonymous
Serveo HTTPS tunnel; a rotating public endpoint triggers a Pages manifest deployment. The computer must stay
awake, logged in, and online. GitHub Pages remains visible during a backend outage but live data cannot.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest service/server/tests -q
npm --prefix service/frontend run build
.\.venv\Scripts\python.exe scripts/verify_end_to_end.py
.\.venv\Scripts\python.exe scripts/verify_browser.py
```

After a genuine strong signal has been published during market hours,
`verify_end_to_end.py --require-stock-signal` also validates its complete format and paper position.

Scanner unit tests mock data only inside the test process; they never insert demo signals. A live validation
runs `stock_scanner.run_scan()` against the real constituent/data/news/Ollama providers and accepts zero
published signals when filters or closed-market freshness rules reject every candidate. Never weaken filters
or inject a fake signal merely to make the UI non-empty.

Known limits: Yahoo Finance and anonymous Serveo are free, unofficial/no-SLA services; universe scraping can
change; headlines are not full-text articles; AI confidence is not calibrated; daily adjusted data does not
capture all intraday regime changes; US holiday detection relies on availability of a fresh intraday quote;
the headline sentiment used for pre-ranking is a lightweight deterministic lexicon; a five-minute monitor can
miss a brief intrabar touch between polls; TP/SL are tracking levels, not standing orders, and the application
does not automatically exit at those levels. This is experimental paper trading, not investment advice.
