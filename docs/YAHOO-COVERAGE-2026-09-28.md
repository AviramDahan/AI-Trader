# Focused Yahoo coverage and metadata — 28 September 2026

Production base d397fe3. This branch is NOT a merge of aa1e675/de4aa4a. Evidence, classification, routing, final stock scanner and other providers stay unchanged.

## Real isolated trial

Three starts 900 seconds apart: 150/150 HTTP 200; zero 429/timeouts/errors. Durations 91.577,78.960,92.555 seconds (mean87.697,max92.555). 288 unique headlines across cycles; 19 fresh observations / 11 distinct fresh headlines. One distinct company verified under production rules, no classified or AI-eligible stock event. No AI calls, public Telegram or production DB writes.

Priority8 open positions + INTC watchlist, no active signals; universe518, rotating pool509. At20/cycle only11 rotate: 47 cycles, worst healthy revisit11h45m. At40/cycle31 rotate:17 cycles/4h15m. At50/cycle41 rotate:13 cycles/3h15m. Requests/hour80/160/200. These bounds exclude provider backoff, delayed scheduling and membership churn; failure latency has no finite guarantee.

## Focused simulation

Same prior frozen historical window. 59 fresh Yahoo canonical events (Yahoo priority path only, age<6h). Original raw relatedTickers were discarded historically; retained query ticker is a known subset because the old fetch required it in relatedTickers. We do NOT reconstruct missing full lists or claim a complete raw-response backtest.

- Identity OLD 10, NEW 18.
- Classified OLD 1, NEW 1.
- AI eligible OLD0, NEW0 (unchanged 12-word excerpt rule).
- Real trial raw metadata provides independent check: 11 fresh unique headlines, identity1→3, classified0→1 (Eaton acquisition), AI eligibility remains0 due absent summaries. No AI invoked.

False-positive review found Starbucks-rival and comparison headlines in the initial candidate implementation; both are explicitly blocked in the final version. Related ticker alone, secondary mentions, generic roundups and bare ambiguous symbols are blocked. Opinion can have correct subject identity but still fails existing classification/evidence; identity is not publication permission.

## All newly identified historical events

- a0924f46e677467d97ad64786658c846: Intel Stock Surged Over 40% in September. History Shows What's Next.
  - INTC / Intel / verified_alias_plus_provider_ticker; publisher Motley Fool; known relatedTicker subset INTC; primary subject PASS; type unknown; evidence sufficient false.
- 6673626727af4b94859647ce35a34c08: Is Amazon Stock a Buy, Hold, or Sell Below $250?
  - AMZN / Amazon / verified_alias_plus_provider_ticker; publisher 24/7 Wall St.; known relatedTicker subset AMZN; primary subject PASS; type unknown; evidence sufficient false.
- 46df2887701f4e738dc5dbda69f460be: Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot
  - LOW / Lowe's / company_name_plus_parenthesized_ticker; publisher Simply Wall St.; known relatedTicker subset LOW; primary subject PASS; type unknown; evidence sufficient false.
- d87f88ad166e48e69291f1bc879ef085: Costco Costs More Than $920 a Share. Here's Why I'd Still Buy One.
  - COST / Costco / verified_alias_plus_provider_ticker; publisher Motley Fool; known relatedTicker subset COST; primary subject PASS; type unknown; evidence sufficient false.
- 4c6f6362da0640cca9a138430bb092e1: Microsoft (MSFT) Reportedly Plans a Vast Data Center Expansion. Can Azure Justify the Cost?
  - MSFT / Microsoft / company_name_plus_parenthesized_ticker; publisher Insider Monkey; known relatedTicker subset MSFT; primary subject PASS; type unknown; evidence sufficient false.
- e4544dee813742248ad5041f77fb7818: Microsoft (MSFT) Puts GitHub’s Coding Engine Inside the App Office Workers Already Use
  - MSFT / Microsoft / company_name_plus_parenthesized_ticker; publisher Insider Monkey; known relatedTicker subset MSFT; primary subject PASS; type unknown; evidence sufficient false.
- 5a1dd7d07f554ceeb2efc993c001b8d6: Oracle’s AI Expansion Faces a New Test as Data Center Costs Rise
  - ORCL / Oracle Corporation / verified_alias_plus_provider_ticker; publisher Insider Monkey; known relatedTicker subset ORCL; primary subject PASS; type unknown; evidence sufficient false.
- 5114e458f3704b2aaf6d57e873f9b324: Oracle (ORCL) Reports a $664 Billion Backlog. Can AI Growth Outpace its Cash Burn?
  - ORCL / Oracle Corporation / company_name_plus_parenthesized_ticker; publisher Insider Monkey; known relatedTicker subset ORCL; primary subject PASS; type unknown; evidence sufficient false.
- 6312882ea01242dc8fbfa8c40452fb20: Everpure (P): Every Analyst Raised Targets After Analyst Day, Free Cash Flow Went Negative Anyway
  - P / Everpure / company_name_plus_parenthesized_ticker; publisher Insider Monkey; known relatedTicker subset P; primary subject PASS; type unknown; evidence sufficient false.
- b58635e1e37c407689635104d062e8cf: Pfizer (PFE) Balances Global Pricing Opportunity with New Revenue Sharing
  - PFE / Pfizer / company_name_plus_parenthesized_ticker; publisher Insider Monkey; known relatedTicker subset PFE; primary subject PASS; type unknown; evidence sufficient false.
- 841eeea8a5e94abf93b75d142a89d633: Carnival (CCL): A Record Quarter Meets a Fuel Bill Nobody Can Hedge Away
  - CCL / Carnival Corporation / company_name_plus_parenthesized_ticker; publisher Insider Monkey; known relatedTicker subset CCL; primary subject PASS; type unknown; evidence sufficient false.

## All real-trial newly identified events

- Dexcom Publishes New Report During EASD 2026 on Type 2 Diabetes Revealing Critical Opportunity for Global Diabetes Care
  - Publisher Business Wire; relatedTickers DXCM, dxcm; DXCM / Dexcom / verified_alias_plus_provider_ticker; primary subject PASS; type unknown.
- Eaton to acquire COL Group for $923m
  - Publisher Power Technology; relatedTickers ETN; ETN / Eaton Corporation / verified_alias_plus_provider_ticker; primary subject PASS; type merger.

## Scope and rollout gate

Recommend focused coverage/metadata rollout after tests: trial transport stable, coverage bottleneck proven, identity improved with reviewed subject protections. No claim of 8–20 messages/day. Metadata hook applies only to Yahoo priority observations with explicit preserved provider_tickers. Historical raw source IDs/content hashes stay unchanged, preventing re-analysis on metadata-only refresh. No schema migration. Compose sets50 and900 seconds explicitly; prior compose/image is rollback. Provider checkpoint adds last-cycle request/success/error/duration/fresh counters for read-only observation of three natural production cycles. Production evidence remains unchanged and no experimental tuning is imported.

