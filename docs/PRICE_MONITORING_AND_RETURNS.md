# Price monitoring and return display

The quote worker stays scheduled throughout trading weekdays (New York calendar), including
outside regular hours. Yahoo 1-minute batch requests now include pre/post-market quotes.
Weekends and known full-day US market holidays skip quote/bar provider calls. Durable bar
cursors are retained; the next trading day catches up completed bars before advancing them.

This is periodic, potentially delayed coverage, not a guaranteed 24-hour live feed. Overnight
prices depend on Yahoo coverage and symbol liquidity. Quote timestamps and stale flags remain
visible in the API; a screen refresh is not a new market observation. Known calendar limitations
include exceptional unscheduled closures and early-close sessions.

Execution policy is unchanged: paper TP/SL and entries use complete regular-session 5-minute
OHLC bars with existing conservative ordering. Extended-hours display quotes do not create fills.
The scanner, news/AI work, and price workers remain independent. No real orders are enabled.

Telegram account return = (cash + marked remaining native positions - initial capital) /
initial capital. It includes closed native trades through cash and all recorded native fees;
it is not a sum or average of position returns. Cash dilutes the overall account percentage.
Show four decimals (or an explicit below-0.0001% label) rather than a misleading rounded zero.
Recent closed native trades display their own net P/L divided by original entry notional.
Legacy and shadow trades remain excluded; no missing historical fills are synthesized.
Only percentages are displayed in the Telegram portfolio, never dollar balances or quantities.
