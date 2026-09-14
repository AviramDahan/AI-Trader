# Local paper operation

This is the upstream React/FastAPI/SQLite application with a small local agent client,
free data fallbacks, and Windows process supervision. It has no brokerage credentials.

## What runs

- Windows task `AI-Trader-Paper`: starts at this user's Windows login, not before login.
  It watches the supervisor process and retries failures up to ten times, one minute apart.
- Supervisor: loopback API, owned Serveo SSH tunnel, and Ollama recovery when needed.
  Local health every ~20 seconds; public HTTPS every ~60 seconds; three failures trigger recovery.
  Tunnel restart means a new hostname. GitHub variable `BACKEND_URL` and the Pages deployment
  are updated. Visitors discover a non-secret `runtime-config.json` every 30 seconds and reload
  after endpoint changes. Recovery includes deployment/CDN delay, generally several minutes.
- Original background tasks: quotes, portfolio metrics, news every 15 minutes, macro/ETF daily-price
  indicators hourly, stock analysis every two hours.
- `ollama-paper-agent`: non-admin, local `qwen3.5:9b-q4_K_M`, one evaluation every 15 minutes.
  Actual news and price observations go to Ollama. Decisions, including HOLD, appear in the
  original Discussions feed and expandable PAPER TRADING ONLY panel. History survives restarts.
  The panel polls every 15 seconds. The original market feeds can refresh more slowly.

## Guardrails

BTC spot paper positions only. Fixed loopback destination; no model-controlled URL or tools.
Maximum $25 virtual order, $100 BTC exposure, four execution attempts per UTC day. No shorts
or leverage. Confidence below 0.75, missing/stale news, invalid JSON or invalid prices prevent
execution. A timeout after an order is sent pauses further orders (`order_pending`) until a human
reconciles the original signals/positions against `.runtime/paper-agent.json`; never blindly retry.
News is untrusted input. Confidence is model-reported, not a calibrated probability or a profit guarantee.
The $25 sizing cap uses the observed quote; execution price movement can slightly change notional.

Sources: BBC Business, Federal Reserve, CoinDesk and US EIA RSS (headlines, source links, original
publication dates; sentiment explicitly unassessed); Yahoo Finance via yfinance for adjusted daily
stock/ETF/BTC series; original Hyperliquid public quotes. ETF 'flows' are the upstream price/volume
proxy, NOT measured institutional fund flows. Low-frequency official news may have older dates.

## Start/stop (PowerShell, repository root)

```powershell
Start-ScheduledTask -TaskName AI-Trader-Paper
.\scripts\stop-ai-trader.ps1
```

Manual start without Windows task: `.\scripts\start-ai-trader.ps1`.
Reinstall login task: `.\scripts\install-ai-trader-autostart.ps1`.
Disable future automatic starts: `Disable-ScheduledTask -TaskName AI-Trader-Paper`.
Re-enable: `Enable-ScheduledTask -TaskName AI-Trader-Paper`.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest service/server/tests -q
npm --prefix service/frontend run build
.\.venv\Scripts\python.exe scripts/verify_end_to_end.py
.\.venv\Scripts\python.exe scripts/verify_browser.py
```

Optional `verify_end_to_end.py --paper-trade` submits one explicitly labelled tiny admin test order.
It does not claim the autonomous AI decided to buy. Browser QA dependencies:
`python -m pip install -r scripts/requirements-qa.txt`, then `python -m playwright install chromium`.

## Limits and recovery

NOT an always-on cloud host: this PC must stay awake, powered, online, and logged in. Nothing changes
the user's global sleep or power policy. Free anonymous Serveo provides no SLA, may show interstitials,
and terminates HTTPS at the provider. A browser interstitial/CORS error is a real outage, not a pass.
Pages remains accessible independently but cannot show live data while the local backend is unreachable.
A stable hosted service/domain would be needed for stronger availability guarantees.

Diagnostics: `.runtime/supervisor.log`, `supervisor-status.json`, `backend.log`, `tunnel.log`, and
`paper-agent.json` (redacted public activity only). The original server logs rotate independently.
Do not expose `.runtime`, `.env`, SQLite or the private backup via static hosting.
Private secrets stay in `PRIVATE_SETUP_CREDENTIALS.txt`, DPAPI encrypted backup, ignored `.env`,
and local SQLite. Newly created credentials are appended without rotating the admin login.
Only `BACKEND_URL` is a GitHub repository variable. No new GitHub secret is necessary.
