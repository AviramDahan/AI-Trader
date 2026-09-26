# Final review preflight and telemetry

The existing ranked top six and thresholds remain unchanged. Skipped candidates
are not replaced by ranks seven and below. No new market-session hard block is
introduced. The existing quote provider, regular-session data selection and
freshness window remain authoritative.

Flow: fresh quote -> direction-specific cooldown -> existing `structure_plan`
and RR validation -> final AI -> schema and semantic checks -> existing confidence,
relevance and sentiment filters -> cooldown again -> fresh quote again -> rebuild
the target plan at that price -> publish the pending paper signal.

Preflight never executes a trade. Existing position execution, exit levels and
accounting are unchanged. Timing is not equivalent to the old path: a quote or RR
failure that might have recovered during inference is now reconsidered on the
next scan; a cooldown may also expire in that interval.

## Provider and failure policy

`STOCK_SCANNER_FINAL_AI_PROVIDER` defaults to `ollama`. The optional
`STOCK_SCANNER_FINAL_AI_MODEL` overrides only final review (not news); otherwise
Ollama uses the existing `OLLAMA_MODEL`. To use OpenRouter, explicitly select
`openrouter`, set its model ID, and store `OPENROUTER_API_KEY` in the private .env.
No provider switch is automatic. Both transports send the same strict schema;
OpenRouter requires parameter support and strict JSON schema. Local validation
also rejects extra fields, missing fields, invalid enums, booleans in numeric
fields, non-finite numbers and out-of-range values. Direction disagreement is
rejected, not repaired. No regex extraction or code-fence recovery is used.

There are at most two HTTP attempts total: one initial attempt and one retry OR
schema repair. Only transient transport failures (timeouts, connection errors,
408/429/500/502/503/504) and invalid schema/JSON permit that second attempt. HOLD,
low confidence, opposing sentiment and semantic direction conflicts never do.
The existing bounded timeout and 450 output-token budget are retained; cloud
reasoning is disabled to match the current `think=False` final-review behavior.

## Private telemetry

The additive `scanner_final_ai_telemetry` table is created by normal database
initialization. Back up the production database before applying this migration.
It does not rewrite historical signals or trades. This change alone does not
restart production or activate OpenRouter.

One UUID record per visited candidate stores scan_id, ticker, one-based rank,
provider/model, token totals, HTTP latency seconds, retry_count, result,
reject_reason, ai_call_saved, estimated_cost (USD), and attempts_json.
The record is written before AI eligibility, after every HTTP attempt and at
final rejection/publication. `attempts_json` preserves each attempt's usage,
latency, result and resolved cloud provider/model when returned. No credentials,
raw source prompts or raw model outputs are stored. The table is not exposed by
the public dashboard API.

`early_skip` records have ai_call_saved=true and no invented tokens or cost.
Unknown usage/cost is NULL, including timeout usage. Aggregate usage is NULL if
any attempt's usage is unknown; known partial usage remains in attempts_json.
OpenRouter cost comes from returned usage.cost; Ollama has no measured monetary
API cost and is NULL. Counts of selected candidates, actually started AI reviews,
and early skips are separate in scanner status. A crash can leave an `eligible`
or `reviewing` record; this is not evidence of zero provider consumption.

Example private analysis (do not count missing usage as free):

```sql
SELECT rank, model, COUNT(*) AS candidates,
       SUM(ai_call_saved) AS skipped_before_ai,
       SUM(CASE WHEN result='signal' THEN 1 ELSE 0 END) AS signals,
       SUM(input_tokens) AS known_input_tokens,
       SUM(output_tokens) AS known_output_tokens,
       SUM(estimated_cost) AS known_cost,
       SUM(CASE WHEN estimated_cost IS NULL THEN 1 ELSE 0 END) AS unknown_cost_rows
FROM scanner_final_ai_telemetry
GROUP BY rank, model;
```

## Monitor isolation and validation

Scanner serialization uses its own lock, not the state-file lock. State-file
locks cover only file access. The position-monitor loop has a dedicated executor,
so scanner/news default-thread-pool congestion cannot queue it behind an AI call.
Every telemetry DB connection/transaction closes before HTTP or retry waiting.
This does not provide separate-process protection from a whole-backend crash.

Run `python -m pytest service/server/tests -q`. The preflight suite mocks all
providers and publication; database tests use a temporary SQLite database. No
live model, trading operation or Telegram delivery is needed. Historical counts
are not backfilled as measured token usage or guaranteed savings.
