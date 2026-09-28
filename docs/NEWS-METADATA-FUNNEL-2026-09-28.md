# News metadata and funnel audit — 28 September 2026

Recommendation: DO NOT DEPLOY. Production d397fe3 unchanged. Experimental baseline d78aeb1.

## Scope and limitations

Fixed window: 2026-09-26 07:39:45.437721 UTC through 2026-09-28 07:39:45.437721 UTC. Retained canonical history begins 2026-09-27 16:37:28 UTC (15.04 hours), not 48 hours of coverage. 1,686 events; 1,316 backlog excluded; 370 non-backlog, of which 340 meet the existing age check at collection. One retained row was updated after cutoff: this is a retrospective simulation, not a perfect point-in-time replay. Membership uses available snapshot state. No AI requests, historical mutations, public Telegram, or production deployment.

Historical raw responses were not retained completely. Metadata fixes cannot be retroactively applied where original fields were discarded. Current live samples establish adapter defects, not additional historical deliveries.

## Funnel

Experimental d78aeb1 versus proposed branch (identity counts include valid market-scope events):

| Stage | d78aeb1 | Proposed |
|---|---:|---:|
| Non-backlog |370|370|
| Fresh at collection |340|340|
| Fresh identity verified / valid market |73|51|
| Fresh and classified |28|28|
| Evidence sufficient |15|15|
| AI eligible |15|15|
| Already analyzed successfully |10|10|
| Existing market deliveries |10|10|
| Known portfolio/watchlist deliveries |0|0|
| Known important-stock deliveries |0|0|

The 15 eligible events comprise 14 existing market AI jobs (10 completed, 2 completion failures, 2 quality rejects) plus one unanalysed DELL stock candidate. DELL was already identity-verified and is NOT one of the 52 identity recoveries. Its relevance/materiality and eventual routing are unknown. No delivery forecast can be inferred without analysis. Existing analyzed market events are not projected stock-topic deliveries.

First-stop partition for all 370 non-backlog events (identity before classification before freshness):

| First stop | d78aeb1 | Proposed |
|---|---:|---:|
| Identity |273|303|
| Classification |64|33|
| Freshness |5|6|
| Evidence |13|13|
| AI eligible |15|15|

No additional first-stop rights/enrichment/budget/scope rejection was identified by this deterministic simulation; downstream relevance/materiality/sentiment cannot be assigned to events never analyzed. Freshness counts in this partition exclude stale events already rejected at an earlier stage.

## Original 52 recoveries

Baseline: 46 classification, 3 freshness, 3 evidence, ZERO AI eligible. Proposed subject guard: 25 identity/primary-subject, 22 classification, 2 freshness, 3 evidence, ZERO AI eligible. The reduced identity count intentionally excludes incidental mentions and conservative ambiguous subjects; it is not a coverage gain.

## Provider metadata

- Yahoo: live HTTP 200 sample of 10 articles contains relatedTickers, publisher, timestamp, URL and title; no summary in inspected examples. Quote objects contain company/exchange but describe the search result, NOT article issuer. Existing scanner helper discarded relatedTickers after filtering. News-only adapter now retains the list; scanner/final-review unchanged. All 1,192 Yahoo + 13 scanner-Yahoo observations already had at least one ticker, but all had empty excerpts. Full historical relatedTickers loss cannot be counted without original responses.
- GlobeNewswire: live HTTP 200, 20 items. Official stock category includes exchange:symbol and domain; publisher/subjects use a different Dublin Core namespace. Fixed stock-category parsing and publisher/subject provenance. Foreign exchange symbols are not mapped to US companies. Historical 58 observations had empty ticker lists; three retained category hints (NYSE:NIO, Nasdaq:HCM, Nasdaq:NXPI) demonstrate discarded candidates, not three verified eligible alerts. Historical category domains were not retained. Five excerpts empty.
- PR Newswire: current read-only probe returned 404; no current raw XML metadata claim is possible. Historical 31 observations had excerpts, empty tickers/categories. No demonstrated structured issuer metadata loss; no provider/config change.
- Investing: live HTTP 200, 10 items, title/link/pubDate/author/enclosure only. No issuer ticker/exchange/CIK or excerpt supplied. All 129 historical observations lack excerpts/tickers; not evidence of adapter loss.
- SEC: live submissions response contains company name, CIK, tickers, exchanges and filing arrays. All 67 retained observations preserve ticker and CIK; company retained in publisher/title. No demonstrated identity loss. Exchange/filing arrays are not all forwarded; 30 excerpts empty.
- Telegram: native message metadata is sender/time/entities, not issuer identity. Code and 79 retained observations preserve message text; ticker lists empty by design. No new Telegram API sample taken; no evidence of discarded structured company ticker/CIK.

Two confirmed adapter-loss classes fixed: Yahoo relatedTickers; GlobeNewswire stock categories and publisher/subject namespace. Structured ticker alone remains insufficient for identity.

## Observed classification gaps and bottleneck

Added only patterns represented in this sample: drone-delivery pilot / redesigned-engine shipment, expansion through a deal, heightened-competition warning, campus sale. Existing analyst patterns cover the First Solar upgrade and TD Synnex price target. Full 21-event review follows below.

Lowe's 46df2887701f4e738dc5dbda69f460be: “Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot”. Classified product; remains evidence-blocked (empty excerpt and unchanged evidence action vocabulary does not recognize starts). This is an evidence-precheck limitation, not proof of low materiality. Lowe's is among the 52, not the original 21 classification rejects.

Amgen 6b4522c1390c46b8b032e47293a63862: campus sale/leaseback classified asset_sale but 11.25 hours old at collection. GE shipment 6.64 hours and S&P Global deal 6.23 hours are also stale under unchanged 6-hour universe policy.

Next bottleneck: sparse Yahoo/Investing evidence plus generic/opinion/roundup headlines, conservative subject verification and arrival age. Existing SEC enrichment requires matching official filing evidence/CIK; it cannot invent a filing for every headline. No enrichment or AI was invoked to manufacture a pass.

## Projection and recommendation

Stock AI eligibility remains ONE candidate across the retained window; the original 52 yield ZERO. At full nominal 48h this is 0.5 stock candidates/day; extrapolating the 15.04h observed span gives 1.60/day, neither is a representative forecast. Known stock-topic deliveries remain zero; DELL outcome unknown. Portfolio/watchlist/day, important-stock/day and total Telegram/day are NOT ESTIMABLE from available analyses. No demonstrated path to 8–20/day. DO NOT DEPLOY; investigate evidence availability/precheck separately, without lowering thresholds.

## All original 52 identity recoveries

Validation: full backend suite 607 passed plus 29 subtests; after adding Yahoo contract parity, targeted metadata/subject suite 13 passed (one additional test). No production AI calls or Telegram sends. False-positive review found incidental Target/Amazon/bank mentions and protected against them. Broad primary-subject heuristics are deliberately conservative and not proven against a representative labelled corpus. No production readiness claim.

Machine-readable first-stop output for all 370 events: NEWS-METADATA-FUNNEL-2026-09-28.csv. This report's 52-event section retains the ORIGINAL recovered cohort, even where proposed primary-subject validation no longer verifies it.

### a0924f46e677467d97ad64786658c846

- Provider: yahoo_priority; publisher: Motley Fool.
- Title: Intel Stock Surged Over 40% in September. History Shows What's Next.
- Identity: INTC / Intel (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 16720dfbace147f58e6062146cd832e7

- Provider: scanner_yahoo, yahoo_priority; publisher: 24/7 Wall St..
- Title: Qualcomm Stock Has an Opportunity Investors May Be Underestimating
- Identity: QCOM / Qualcomm (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 0bebf5e1e7334a1dbc57f38c8efa032b

- Provider: scanner_yahoo, yahoo_priority; publisher: 24/7 Wall St..
- Title: Starbucks Will Close 250 Stores. His $20,000 401(k) Loan Won’t Count Against Social Security’s Earnings Test, but It Could Make More of His Benefit Taxable
- Identity: SBUX / Starbucks (verified_alias_plus_provider_ticker).
- Baseline type: earnings; next rejection: stale.
- Proposed type: earnings; next rejection: stale.

### cf9ec010c3db40a9b1fabfb7d8076ce2

- Provider: scanner_yahoo, yahoo_priority; publisher: Business Wire.
- Title: Giant Pandas Ping Ping and Fu Shuang Arrive in Atlanta on the FedEx Panda Express
- Identity: FDX / FedEx (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### c380a54d59364a45b0b2e973b44dcb65

- Provider: yahoo_priority; publisher: Pioneer Press, St. Paul, Minn..
- Title: Business People: Evereve hires Target exec Alanna Baker to lead digital
- Identity: TGT / Target Corporation (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### d58e8e34814745508e16bb1ac6b022bf

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Coinbase (COIN) vs Strategy (MSTR): Which is a Better Stock to Buy?
- Identity: COIN / Coinbase (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 548750d3636c4e43bf8b16294b66dd2b

- Provider: yahoo_priority; publisher: Motley Fool.
- Title: History Says Intel's Best Years Have Been Hard to Follow. 2026 Is Its Best in More Than 4 Decades.
- Identity: INTC / Intel (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 6673626727af4b94859647ce35a34c08

- Provider: yahoo_priority; publisher: 24/7 Wall St..
- Title: Is Amazon Stock a Buy, Hold, or Sell Below $250?
- Identity: AMZN / Amazon (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 46df2887701f4e738dc5dbda69f460be

- Provider: scanner_yahoo, yahoo_priority; publisher: Simply Wall St..
- Title: Lowe's Companies (LOW) Starts 20 Minute Drone Delivery Pilot
- Identity: LOW / Lowe's (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: product; next rejection: insufficient_information.

### d87f88ad166e48e69291f1bc879ef085

- Provider: yahoo_priority; publisher: Motley Fool.
- Title: Costco Costs More Than $920 a Share. Here's Why I'd Still Buy One.
- Identity: COST / Costco (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### d7f644954c6241d2966cfa3d15a3262e

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Why is Intel Corporation (INTC) up over 33%? Is the Rally Sustainable?
- Identity: INTC / Intel (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 0d6a5b1d2ea6430fb24effd115e20072

- Provider: yahoo_priority; publisher: TheStreet.
- Title: Walmart, Aldi, and Kroger follow Costco's lead
- Identity: KR / Kroger (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 77003624bba443a4957410cfe19d3dc5

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Pfizer vs. Medtronic: Which Healthcare Turnaround is More Convincing?
- Identity: MDT / Medtronic (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 808b87f800c04b4fa30fcf4626c5898b

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Gilead vs. Medtronic: Which Healthcare Stock Offers the Better Mix of Growth and Income?
- Identity: MDT / Medtronic (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 4c6f6362da0640cca9a138430bb092e1

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Microsoft (MSFT) Reportedly Plans a Vast Data Center Expansion. Can Azure Justify the Cost?
- Identity: MSFT / Microsoft (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### e4544dee813742248ad5041f77fb7818

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Microsoft (MSFT) Puts GitHub’s Coding Engine Inside the App Office Workers Already Use
- Identity: MSFT / Microsoft (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 14f93f0b928a43279282f9288e8f090e

- Provider: yahoo_priority; publisher: Motley Fool.
- Title: If You'd Invested $10,000 in Netflix (NFLX) 5 Years Ago, Here's How Much You'd Have Today
- Identity: NFLX / Netflix (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### a7930261f6e043fca510c8bd143c81fa

- Provider: yahoo_priority; publisher: Motley Fool.
- Title: Elon Musk Just Gave Nvidia Investors More Good News. Is the Stock a Buy?
- Identity: NVDA / Nvidia (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### b254983f668c4755a44196b538ba9df0

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Robinhood (HOOD) Pushes Beyond Trading. Can Wealth Management Bring Steadier Revenue?
- Identity: HOOD / Robinhood Markets (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 5a1dd7d07f554ceeb2efc993c001b8d6

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Oracle’s AI Expansion Faces a New Test as Data Center Costs Rise
- Identity: ORCL / Oracle Corporation (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 672cb8294e7e420b99d6520c4def87a4

- Provider: yahoo_priority; publisher: TheStreet.
- Title: Michael Burry just put a date on Big Tech's AI reckoning, and Oracle's $664 billion lands in crosshairs
- Identity: ORCL / Oracle Corporation (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 5114e458f3704b2aaf6d57e873f9b324

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Oracle (ORCL) Reports a $664 Billion Backlog. Can AI Growth Outpace its Cash Burn?
- Identity: ORCL / Oracle Corporation (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 6312882ea01242dc8fbfa8c40452fb20

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Everpure (P): Every Analyst Raised Targets After Analyst Day, Free Cash Flow Went Negative Anyway
- Identity: P / Everpure (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### b12e94aaf1de4218a6503dd5ecf17c66

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Gilead’s HIV Concentration or Pfizer’s Patent Cliff: Which Risk is Easier to Own?
- Identity: PFE / Pfizer (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### bd20c6a898094917ae7a68e24353e88c

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Pfizer vs. Thermo Fisher: Which Healthcare Turnaround has More Upside?
- Identity: PFE / Pfizer (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### b58635e1e37c407689635104d062e8cf

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Pfizer (PFE) Balances Global Pricing Opportunity with New Revenue Sharing
- Identity: PFE / Pfizer (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### f46f53abdf7849edaa2787c10a736adb

- Provider: scanner_yahoo, yahoo_priority; publisher: TheStreet.
- Title: Starbucks rival cafe chain has closed 130 locations
- Identity: SBUX / Starbucks (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 49f8faeaf72b41a48be4f0a48622ff34

- Provider: yahoo_priority; publisher: Barchart.
- Title: How to Trade Qualcomm Stock Near Multi-Month Highs
- Identity: QCOM / Qualcomm (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### f91014bdbe034f26abeeb614ec8bcd5f

- Provider: scanner_yahoo, yahoo_priority; publisher: LA Times.
- Title: Did your favorite local Starbucks just close? These 36 SoCal locations are likely shuttered
- Identity: SBUX / Starbucks (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### b14d75f8d902402694a2dd8eb0a7f149

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Is Synopsys (SNPS) a Breakout Play as Headwinds Subside and BNP Paribas Upgrades?
- Identity: SNPS / Synopsys (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 36d5f05774d24019b836b5dcd4afd4be

- Provider: yahoo_priority; publisher: Investor's Business Daily.
- Title: Dow Jones Futures Fall, Oil Prices Rise Amid Trump Iran Comments; Micron, SpaceX, Tesla Eye Buy Points
- Identity: TSLA / Tesla, Inc. (verified_alias_plus_provider_ticker).
- Baseline type: market; next rejection: insufficient_information.
- Proposed type: market; next rejection: insufficient_information.

### 44cb5edbcec14cd581581e50bc5991ca

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Can Costco (COST) and Uber (UBER) Make Warehouse Delivery Economically Attractive?
- Identity: COST / Costco (company_name_plus_parenthesized_ticker); UBER / Uber (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 474a278a4907445c951cd1df627be06d

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Is the Beauty Aisle Becoming Retail’s Next Big Battleground for Walmart (WMT) and Ulta (ULTA)?
- Identity: WMT / Walmart (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 4e05340ae8af449ca28c92b4a5148544

- Provider: yahoo_priority; publisher: Motley Fool.
- Title: SpaceX vs. Tesla: Which Will Be the Largest Company at the End of 2027?
- Identity: TSLA / Tesla, Inc. (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 7216298f71ec4c2d8ea940dbaa5cc468

- Provider: yahoo_priority; publisher: Simply Wall St..
- Title: The Bull Case For Waters (WAT) Could Change Following New At-Home HPV And Cell Analysis Push
- Identity: WAT / Waters Corporation (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### c3a1d144f9234c0c9fb4aa5401ae45f0

- Provider: yahoo_priority; publisher: Simply Wall St..
- Title: Insperity (NSP) Expands HRScale With Workday, Is The Stock Still Cheap?
- Identity: WDAY / Workday, Inc. (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 5de95a0e733c411fb5c829ca0d9c9dc9

- Provider: scanner_yahoo; publisher: Benzinga.
- Title: Starbucks to Close Select North America Coffeehouses, Cuts Store Outlook
- Identity: SBUX / Starbucks (verified_alias_plus_provider_ticker).
- Baseline type: guidance; next rejection: insufficient_information.
- Proposed type: guidance; next rejection: insufficient_information.

### 67df50b9a56d4b2da4c28ff9d333ec8f

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Target’s Dividend Has Room to Grow, But Capital Spending Matters
- Identity: TGT / Target Corporation (verified_alias_plus_provider_ticker).
- Baseline type: capital_return; next rejection: stale.
- Proposed type: capital_return; next rejection: identity_unverified.

### 841eeea8a5e94abf93b75d142a89d633

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Carnival (CCL): A Record Quarter Meets a Fuel Bill Nobody Can Hedge Away
- Identity: CCL / Carnival Corporation (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### cc2ce5208f604c6eb98c73a0eb7927b8

- Provider: yahoo_priority; publisher: Simply Wall St..
- Title: Target (TGT) Stock Still Looks Below Fair Value Following Merchandising Refresh
- Identity: TGT / Target Corporation (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### f4b0ac677ec046b19d2b40ef3a41d289

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Airbnb (ABNB): Is ABNB’s Strong Growth Story Already Priced Into the Stock?
- Identity: ABNB / Airbnb (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 8c9b88b423c94197aca507e687567279

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: AI Could Give AbbVie (ABBV) a New Route to Long-Term Pipeline Growth
- Identity: ABBV / AbbVie (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 38c42e1a70da4fa8a2b9b33010f9a9aa

- Provider: yahoo_priority; publisher: PR Newswire.
- Title: Arcadis deepens Autodesk collaboration to accelerate AI and data-led delivery for clients
- Identity: ADSK / Autodesk (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### cb8017872b8e40859f6bf2be82d2a3ed

- Provider: yahoo_priority; publisher: Zacks.
- Title: Nvidia, Micron, Alphabet, Oracle and Adobe are part of Zacks Earnings Preview
- Identity: ADBE / Adobe Inc. (verified_alias_plus_provider_ticker).
- Baseline type: earnings; next rejection: insufficient_information.
- Proposed type: earnings; next rejection: identity_unverified.

### 8c96fdc98f3c47e8b969bc674f2d5f74

- Provider: yahoo_priority; publisher: Barchart.
- Title: The AI Fear That Crushed Accenture Just Created Its Biggest Opportunity. Here’s What The Anthropic Partnership Means.
- Identity: ACN / Accenture (verified_alias_plus_provider_ticker).
- Baseline type: business_update; next rejection: stale.
- Proposed type: business_update; next rejection: identity_unverified.

### 0dfd48606d2948558c5f41520391ace7

- Provider: yahoo_priority; publisher: Barchart.
- Title: Is Allegion Underperforming the Nasdaq?
- Identity: ALLE / Allegion (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 6b4522c1390c46b8b032e47293a63862

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Amgen (AMGN) Sells its Deerfield Campus for $151 Million and Leases it Back
- Identity: AMGN / Amgen (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: asset_sale; next rejection: stale.

### 101d25fb6b254a9ca294698554f9348c

- Provider: yahoo_priority; publisher: Moneywise.
- Title: Seattle tower across from Amazon sold for $12.5M after a $97M deal in 2019. Where smart real estate money is going now
- Identity: AMZN / Amazon (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: identity_unverified.

### 02e6bac181674f16bf5de148c460e932

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Amazon (AMZN) Calls for AI Safeguards Without a Slowdown. Can AWS Benefit?
- Identity: AMZN / Amazon (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 996a28789c6d4f71ae7e3973b471b5f6

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Amazon (AMZN) Pauses a Cargo Carrier after a Fatal Crash. Can its Air Network Absorb the Disruption?
- Identity: AMZN / Amazon (company_name_plus_parenthesized_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 5cb4a8343d1e405d9e19b3517f3987eb

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Amazon Taps Prysmian and Rio Tinto for Low-Carbon Data Center Cables. What Does it Mean for Investors?
- Identity: AMZN / Amazon (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

### 11530101ecb040b1a4e500928c61fe4f

- Provider: yahoo_priority; publisher: Insider Monkey.
- Title: Why Amgen’s Pipeline Just Got More Interesting
- Identity: AMGN / Amgen (verified_alias_plus_provider_ticker).
- Baseline type: unknown; next rejection: unsupported_or_noise.
- Proposed type: unknown; next rejection: unsupported_or_noise.

## All 21 original classification rejects

- **6a8b972358174afb8d8d6f78c023967a** — Kinder Morgan (KMI) Could Be 14% Undervalued Following Its Recent Pullback
  - Provider: yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 1.03h.
- **d4b07380187e47ee870de15ce5b5e93b** — Lockheed Martin (LMT) Gets Another Boost from the Long-Range Missile Push
  - Provider: scanner_yahoo, yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 3.4h.
- **e09d4e9467ae4627a788e294eea3b658** — Goldman Sachs Looks to Deepen its Footprint in Credit
  - Provider: scanner_yahoo, yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 2.46h.
- **97c6fc3abb7d4a5484dffe6e42e3eefe** — Dell Technologies general counsel sells $2.33m in shares
  - Provider: investing. Proposed type: insider_transaction; first stop: AI_eligible; age at collection: 0.21h.
- **0bb6290206244081929be8ed58078b61** — Gilead or Johnson & Johnson: Is Faster Growth Better than Greater Diversification?
  - Provider: yahoo_priority. Proposed type: unknown; first stop: identity_unverified; age at collection: 0.44h.
- **0fbd895e199f4941af7a23fa6ea78c6a** — Why Meta Platforms Stock Jumped 13% This Week
  - Provider: yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 3.66h.
- **ae90fcb854534440b338e176e91c0522** — GE Aerospace (GE) Ships Redesigned Engines to Boeing (BA). Can it Keep the 777X on Track?
  - Provider: scanner_yahoo, yahoo_priority. Proposed type: product; first stop: stale; age at collection: 6.64h.
- **1e05ad15ff15483daee9a640679b8a3f** — Prediction: ON Semiconductor Could Be a Sleeper AI Infrastructure Winner
  - Provider: yahoo_priority. Proposed type: unknown; first stop: identity_unverified; age at collection: 7.69h.
- **6c1aeded6c424ea290dc9df9f162a81d** — The AI Security Opportunity Emerging for Palo Alto Networks
  - Provider: yahoo_priority. Proposed type: unknown; first stop: identity_unverified; age at collection: 4.9h.
- **2616cd02b7aa4e8a8264ee3ab1016cbc** — Salesforce vs. Palantir Technologies: What Revenue Trends Reveal to Investors About These Tech Giants
  - Provider: yahoo_priority. Proposed type: unknown; first stop: identity_unverified; age at collection: 2.13h.
- **597f9c18a2f54bfa9f0c70e741f75669** — TD Synnex: Morgan Stanley lifts price target after strong quarter
  - Provider: investing. Proposed type: price_target; first stop: identity_unverified; age at collection: 0.1h.
- **6cf7600a880849df8f44020288ac4b3c** — S&P Global Expands into Onchain Finance with OpenZeppelin Deal
  - Provider: yahoo_priority. Proposed type: business_update; first stop: stale; age at collection: 6.23h.
- **ee949ccbffe045cf8c1853013d96385d** — Morgan Stanley says Robinhood quietly built something bigger ahead of its September Summit
  - Provider: scanner_yahoo. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 0.56h.
- **b89d72b135c449f89eba2a382184b696** — Is T. Rowe Price Group (TROW) Worth More Than Its Price?
  - Provider: yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 6.92h.
- **3202f6343c654b77904726edad87562f** — Western Digital Stock Is Just One Of 3 Top AI Infrastructure Picks
  - Provider: yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 2.89h.
- **87f5d0ded84a4e1799475459178d92d6** — Micron Technology (MU) is Printing Cash. Can its Memory Momentum Last?
  - Provider: scanner_yahoo. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 0.65h.
- **d72dc554727f45299f84395a37b70910** — Is Wynn Resorts Stock Underperforming the Dow?
  - Provider: yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 8.13h.
- **01952c4877dc4d2f8feba62f45aa4d65** — Can General Motors’ (GM) New V-8s Protect Truck Profits without Derailing its EV Strategy?
  - Provider: yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 5h.
- **cd1984a452b147e7a3a0de6f8f3d8e89** — Bristol Myers Squibb vs. Novo Nordisk: Which Healthcare Stock Is a Better Buy in 2026?
  - Provider: yahoo_priority. Proposed type: unknown; first stop: unsupported_or_noise; age at collection: 8.09h.
- **14a674eb971e4383856957fcebe3530a** — KeyBanc upgrades First Solar stock rating on valuation
  - Provider: investing. Proposed type: analyst_rating; first stop: insufficient_information; age at collection: 0.08h.
- **cc63dc7d413f41eea9fad259ece8b759** — General Motors warns of heightened U.S. competition as China risks grow- FT
  - Provider: investing. Proposed type: business_risk; first stop: insufficient_information; age at collection: 0.14h.
