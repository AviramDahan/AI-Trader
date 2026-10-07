Signal research dashboard
=========================

The public scanner exposes ``GET /api/scanner/research?hours=24|48|168``.
The status tab shows a decision summary, the research tab shows recorded
candidate checks and saved levels, and results show percentage/R outcomes.
The endpoint opens a read-only repeatable-read PostgreSQL transaction with an
eight-second statement timeout. SQLite uses query_only. Each source is capped
at 5,000 rows independently, including each journal stage; hitting the cap is
explicit. Total scan/ticker observation and unique ticker counts use SQL across
the full window. Detail-derived metrics are labelled as a bounded sample. The
200 candidate records prioritize decisions/target checks, then newest records,
and 200 outcome details are rendered; summaries use the bounded full sample.
The endpoint performs no initialization, trading writes, provider/AI calls,
or Telegram operations. No schema migration or worker changes are required.

Interpretation
--------------

Counts are scan/ticker observations, not independent trading opportunities.
Unique tickers and exact reference-price/source geometry configurations are
reported separately. These configurations are not an estimate of unique setups.
Stages need not form a nested funnel: target prechecks, telemetry and signals
have different recording coverage. Missing technical/news stages are not
reconstructed. AI attempts are counted from persisted per-review attempts;
they can include pre-request failures and are not billed-call counts. Validated
responses are counted separately, without exposing prompts or model output;
no hypothetical model decisions are added. Rejection reasons are exact saved
codes; combined AI/confidence/relevance reasons cannot be split retroactively.
Quote absences are classified using the existing regular-session calendar at
the saved observation time, without changing extended-hours execution policy.

The level diagram displays saved reference entry, stop, target and resistance.
It fetches no current chart data and invents no historical candle/pivot.
Signal qualification is distinct from allocation/execution status. A blocked
allocation is not a failed signal-quality decision or an activated position.

Outcomes use actual original quantity, original price risk and recorded fills.
Partial exits are weighted by original quantity. Recorded fees are subtracted
once; price slippage is already in fills and is not subtracted again. Realized
net includes fees already paid, including the entry fee. Open marks are gross
on remaining quantity from completed monitor bars, with completion time and
stale indication; combined marks deduct paid fees only, not estimated future
exit costs. Short borrow costs are not modelled. Group means use closed trades
with complete entry, quantity, fee and realized-PnL evidence. Null is unavailable,
not zero. Legacy remains excluded from verified metrics, and Shadow is a signal
comparison without independent capital. Closed outcomes from the window and
currently open positions are shown, including those entered before the window.
Signal sums/means are not portfolio returns. MFE/MAE are unavailable until a
suitable retained historical price path exists; no historical path is invented.

Release scope
-------------

This change is an additive read-only API and presentation update. Existing
news, AI, thresholds, targets, order lifecycle, sizing, accounting, Telegram,
and Position Monitor policy are untouched. Normal main CI/readiness gates
remain required for any separately approved production release. An old
frontend keeps using the existing dashboard; an old backend makes the new
panel explicitly unavailable instead of fabricating statistics.
