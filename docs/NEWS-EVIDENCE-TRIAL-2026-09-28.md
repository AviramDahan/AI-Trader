# Evidence sufficiency trial — 28 September 2026

Recommendation: DO NOT DEPLOY. Baseline aa1e675. No production, AI, Telegram, threshold, routing, strategy or provider-configuration changes.

Tests: backend regression suite 626 passed + 29 subtests (two dependency deprecation warnings). Final targeted evidence suite 19 passed after adding a guard against fabricated structured claims; simulation rerun unchanged. RSS combined-field retention is fixture-verified, not a claim of newly fetched historical content. Evidence trial remains offline, not production-wired.

## Window / interpretation

Same frozen window: 2026-09-26T07:39:45.437721Z through 2026-09-28T07:39:45.437721Z. Retained history spans only 15.04h. One retained row changed after cutoff; snapshot is not exact point-in-time replay. Freshness uses collection time and existing portfolio/universe age rules, not today's time. 370 non-backlog / 340 fresh.

## Funnel

340 fresh → 51 identity-verified or market → 28 classified → OLD evidence/AI 15 → NEW evidence/AI 16.

- OLD: stock 1 (DELL), market 14.
- NEW: stock 2 (LOW, SBUX), market 14 unchanged.
- Recovered stock events: 2 GOOD for minimum AI input, 0 QUESTIONABLE, 0 FALSE POSITIVE in this tiny manual review. GOOD is not source-fact verification, high materiality, or publication approval.
- DELL is newly blocked: title-only Investing with no corroborating source, as required in this task. Net gain = 1, not +2.
- 13 old evidence blocks: Yahoo paths 4 unique events (5 observations: LOW appears twice); Investing 9 events. PR Newswire 0; GlobeNewswire 0; SEC 0; Telegram 0 at this stage. Earlier identity/classification exclusions are NOT evidence successes.
- All 13 have excerpt length 0, no stored structured claims and no source event_refs. No primary-source URL is established in these 13. LOW has two ingestion observations of the SAME Yahoo URL, not independent corroboration. Others have no alternate observation. No hidden substantive body was found in retained normalized evidence.

## Deterministic trial

Implemented offline assess() with explicit flags: verified identity, known event type, approved source provenance, valid explicit publication time, source URL, structured metadata, concrete type-specific factual clause, numeric fact and distinct URLs. Publication time supplies reporting context, not proof of when the underlying event happened.

No 12-word acceptance shortcut. Long vague excerpts fail. Specific title can provide minimum what; verified company and timestamp/provenance provide who/context. Canonical observations are assessed together; a company-linked alternate excerpt may supply the factual clause. Partial fragments are NOT concatenated into invented facts. Repeated sources/URLs are not scored as confirmation. No numerical confidence score or source-count threshold.

Only known canonical membership and company-linked evidence are used. This does not change dedupe, rights, conflicts, freshness or downstream validators. Title-only Investing and unsupported social relay remain blocked. Market evidence rules are explicitly unchanged (this experiment targets stock news).

This is a limited typed-fact prototype, not an exhaustive factual-language classifier. Unknown phrasing remains fail-closed. A broad rollout would need a larger labelled sample and source provenance review. It is NOT wired into runtime eligibility.

## Provider content audit

- Yahoo: summary when explicitly supplied, publisher, URL, published time and relatedTickers are preserved by the experimental news-only adapter. The prior live sample supplied no summary. No article bodies invented or article-page scraping. Search quote metadata is not issuer evidence.
- GlobeNewswire / PR Newswire: fixed RSS extraction on the branch to retain distinct description + content:encoded + Atom summary/content, instead of discarding later fields when description exists. Fixture verifies this. Historical raw XML is unavailable, so this fix contributes ZERO assumed historical candidates. Existing response/evidence limits remain. No article-page fetches.
- Investing: no excerpt/ticker invented; standalone title cannot pass this trial. Alternate canonical evidence may satisfy it.
- SEC: existing enrichment untouched; no enrichment requests in this run.
- Telegram: retained factual text remains available, but relay-only claims do not independently establish verification. No new Telegram fetch.

## Recovered event quality review

### 46df2887701f4e738dc5dbda69f460be — GOOD (minimum input only)

- LOW / Lowe's
- Title: Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot
- Providers: scanner_yahoo, yahoo_priority; publisher: Simply Wall St..
- Type: product.
- Old block: empty excerpt; unchanged short-evidence gate required additional facts/action vocabulary. LOW's starts action was not recognized; SBUX lacked extra excerpt/numeric facts.
- New basis: specific product action in title + verified subject/ticker + source/publisher + publication timestamp. Not an automatic Telegram decision.
- Evidence: title: Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot

### 5de95a0e733c411fb5c829ca0d9c9dc9 — GOOD (minimum input only)

- SBUX / Starbucks
- Title: Starbucks to Close Select North America Coffeehouses, Cuts Store Outlook
- Providers: scanner_yahoo; publisher: Benzinga.
- Type: guidance.
- Old block: empty excerpt; unchanged short-evidence gate required additional facts/action vocabulary. LOW's starts action was not recognized; SBUX lacked extra excerpt/numeric facts.
- New basis: specific guidance action in title + verified subject/ticker + source/publisher + publication timestamp. Not an automatic Telegram decision.
- Evidence: title: Starbucks to Close Select North America Coffeehouses, Cuts Store Outlook

## Every insufficient-information event

### 46df2887701f4e738dc5dbda69f460be

- Title: Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot
- Company: LOW / Lowe's.
- Type: product; published: 2026-09-27T19:11:29+00:00.
- Exact old gate: No excerpt, starts not in prior action vocabulary; numeric 20 Minute does not match prior numeric-fact units.
- New result: FACTUAL_MINIMUM_EVIDENCE; eligible=true.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: yahoo_priority; publisher=Simply Wall St.; excerpt chars=0; tickers=LOW; CIK=none; raw metadata keys=id; structured claims=0; event refs=0. URL: https://finance.yahoo.com/markets/stocks/articles/lowes-companies-low-starts-20-191129203.html
- Observation: scanner_yahoo; publisher=Simply Wall St.; excerpt chars=0; tickers=LOW; CIK=none; raw metadata keys=id; structured claims=0; event refs=0. URL: https://finance.yahoo.com/markets/stocks/articles/lowes-companies-low-starts-20-191129203.html

### 0d03259ac22c43a49e467d9694ec9535

- Title: Trump: Oil prices will plummet after war ends ‘very soon’
- Company: not verified; market scope.
- Type: market; published: 2026-09-27T21:52:29+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/economy-news/iran-says-it-wont-soften-hormuz-demands-after-trump-rejects-proposal-4918887

### 5dbefd928a094d2a9f0328810da7c553

- Title: GE Aerospace Is Spending $12 Billion on an Acquisition. Is It Still the Best Aerospace Stock to Own?
- Company: GE / GE Aerospace.
- Type: merger; published: 2026-09-27T20:50:00+00:00.
- Exact old gate: Question/opinion headline excluded; no excerpt with factual acquisition details.
- New result: no_specific_factual_clause_or_missing_event_detail; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: yahoo_priority; publisher=Motley Fool; excerpt chars=0; tickers=GE; CIK=none; raw metadata keys=id; structured claims=0; event refs=0. URL: https://finance.yahoo.com/markets/stocks/articles/ge-aerospace-spending-12-billion-205000377.html

### 9bca3c16c232445fa359079f97372917

- Title: Japan’s corporate services inflation hits 2-year high
- Company: not verified; market scope.
- Type: market; published: 2026-09-28T00:30:49+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/economy-news/japans-corporate-services-inflation-hits-2year-high-4919220

### 70b2a2c7ba67430e91a6bbfe3c43b9bd

- Title: Brent rises above $107/bbl as Iran, U.S. remain at odds over Hormuz reopening
- Company: not verified; market scope.
- Type: market; published: 2026-09-28T01:25:33+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/commodities-news/oil-prices-rise-as-iran-us-remain-at-odds-over-hormuz-reopening-4919238

### 36d5f05774d24019b836b5dcd4afd4be

- Title: Dow Jones Futures Fall, Oil Prices Rise Amid Trump Iran Comments; Micron, SpaceX, Tesla Eye Buy Points
- Company: not verified; market scope.
- Type: market; published: 2026-09-28T02:54:07+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: yahoo_priority; publisher=Investor's Business Daily; excerpt chars=0; tickers=TSLA; CIK=none; raw metadata keys=id; structured claims=0; event refs=0. URL: https://finance.yahoo.com/m/473106f6-6763-38d5-b898-3f7ff08d4b61/dow-jones-futures-fall%2C-oil.html

### d1d9a0dd4265467c9d55c7c758eabc1e

- Title: China, US agree tariff cuts on $60 billion of goods including agriculture, household items
- Company: not verified; market scope.
- Type: market; published: 2026-09-28T03:12:52+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/commodities-news/china-says-us-trade-truce-extension-creates-space-to-advance-talks-4919293

### 782cf577cd79477fb042736775b0f574

- Title: RBA preview September: 25 bps widely expected as inflation risks grow
- Company: not verified; market scope.
- Type: market; published: 2026-09-28T03:21:03+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/economy-news/rba-preview-september-25-bps-widely-expected-as-inflation-risks-grow-4919297

### 7f65267efad84b67ba2ff37fb029b534

- Title: China to cut tariffs on US farm goods, but list excludes soybeans
- Company: not verified; market scope.
- Type: market; published: 2026-09-28T04:24:27+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/commodities-news/china-says-to-cut-tariffs-on-us-farm-goods-but-soybeans-excluded-4919307

### 5de95a0e733c411fb5c829ca0d9c9dc9

- Title: Starbucks to Close Select North America Coffeehouses, Cuts Store Outlook
- Company: SBUX / Starbucks.
- Type: guidance; published: 2026-09-28T03:30:06+00:00.
- Exact old gate: Recognized cuts action but no extra excerpt terms, qualifying numeric fact or grounded claim.
- New result: FACTUAL_MINIMUM_EVIDENCE; eligible=true.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: scanner_yahoo; publisher=Benzinga; excerpt chars=0; tickers=SBUX; CIK=none; raw metadata keys=id; structured claims=0; event refs=0. URL: https://finance.yahoo.com/markets/stocks/articles/starbucks-close-select-north-america-033006837.html

### cd3bc13691b441b19ff130472449e104

- Title: China to cut tariffs on host of U.S. agrigoods, but soybeans not included
- Company: not verified; market scope.
- Type: market; published: 2026-09-28T05:31:15+00:00.
- Exact old gate: Market has no excerpt; stock-only short-evidence exception does not apply.
- New result: market_unchanged; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/economy-news/china-to-cut-tariffs-on-host-of-us-agrigoods-but-soybeans-not-included-4919337

### 14a674eb971e4383856957fcebe3530a

- Title: KeyBanc upgrades First Solar stock rating on valuation
- Company: FSLR / First Solar.
- Type: analyst_rating; published: 2026-09-28T06:22:48+00:00.
- Exact old gate: No excerpt/grounded claim/extra facts; no qualifying specific detail.
- New result: no_usable_company_linked_evidence; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/analyst-ratings/keybanc-upgrades-first-solar-stock-rating-on-valuation-93CH-4919375

### cc63dc7d413f41eea9fad259ece8b759

- Title: General Motors warns of heightened U.S. competition as China risks grow- FT
- Company: GM / General Motors.
- Type: business_risk; published: 2026-09-28T06:50:36+00:00.
- Exact old gate: No excerpt/grounded claim/extra facts; no qualifying specific detail.
- New result: no_usable_company_linked_evidence; eligible=false.
- Primary source URL: not established. Alternate substantive evidence: none retained.
- Observation: investing; publisher=Investing.com; excerpt chars=0; tickers=none; CIK=none; raw metadata keys=id,categories,timestamp_source,source_timezone,timezone_resolution,original_timestamp,activation_boundary; structured claims=0; event refs=0. URL: https://www.investing.com/news/stock-market-news/general-motors-warns-of-heightened-us-competition-as-china-risks-grow-ft-93CH-4919425

## Next bottleneck / projection

Only 5 of the 13 evidence-blocked events are stock events; 8 are market events. Of the 5, two recover, GE remains an opinion/question without acquisition details, and FSLR/GM remain title-only Investing with no alternate evidence. Even accepting all five (not recommended) would not reach 8–20 additional stock candidates in this window. The upstream ceiling is 6 fresh classified stock events including DELL; 22 classified market events account for the rest of the 28.

The remaining bottleneck is upstream stock coverage/identity/classification and substantive company-news content, not a generic 12-word gate alone. 340 fresh minus 51 identified/market = 289 blocked at identity, then 23 more at classification. This does not justify relaxing identity: many are foreign companies, general headlines, secondary mentions or opinion. No thresholds changed.

Projected stock AI candidates/day: insufficient representative data. Mechanical 2 candidates / nominal 48h = 1/day; using only observed 15.04h gives 3.19/day. Neither is a reliable forecast. Projected Telegram messages/day: unknown (no new relevance/materiality analyses). New AI requests and spend: zero. No public messages, historical writes or production deployment.
