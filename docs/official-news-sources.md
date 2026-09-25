# Official news sources

AI-Trader polls these public, free endpoints from the backend. It stores the original publisher, direct URL, original publication time, collection time, and whether only feed metadata was available. Hebrew text is clearly labelled as an AI translation/interpretation; the original title and link remain authoritative. A missing published time is rejected rather than replaced with collection time.

| Provider | Endpoint and coverage | Operational limits and attribution |
| --- | --- | --- |
| SEC EDGAR | [Submissions API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), `data.sec.gov/submissions/CIK##########.json`, plus the latest-100 EDGAR Atom feed | No key. An identifying `NEWS_SEC_USER_AGENT` is required. Requests share a conservative rate limiter, use conditional caching and a bounded number of CIKs per cycle. Open positions/watchlist are prioritised. SEC is credited as source and the filing URL is preserved. |
| FDA | [FDA RSS catalogue](https://www.fda.gov/about-fda/contact-fda/subscribe-podcasts-and-news-feeds), official press-release RSS | No published quota was found; this is not treated as unlimited access. Polled conditionally at the configured feed cadence. FDA is credited and its direct URL is preserved. Dashboard ingestion only; no automatic Telegram alert. |
| FTC | [FTC RSS catalogue](https://www.ftc.gov/stay-connected/rss), general, Consumer Protection and Competition press-release feeds | No published quota was found; conditional requests, backoff and the configured cadence are used. FTC is credited and its direct URL is preserved. Dashboard ingestion only; no automatic Telegram alert. |
| DOJ | [DOJ News API](https://www.justice.gov/developer/api-documentation/api_v1), latest press releases | Maximum 50 results per request; the official documentation warns that more than four requests per second may be degraded or blocked. AI-Trader makes one cached request per feed cycle. DOJ is credited and its direct URL is preserved. Dashboard ingestion only; no automatic Telegram alert. |
| EIA | [EIA RSS catalogue](https://www.eia.gov/tools/rssfeeds/), Today in Energy and press-release feeds | No published quota was found; conditional requests, backoff and the configured cadence are used. EIA is credited and its direct URL is preserved. Dashboard ingestion only; no automatic Telegram alert. |

The Federal Reserve, BLS, Yahoo-priority and existing-market sources remain in place. Company ticker assignment is never inferred from a common ticker word. General regulatory, industry or macro releases remain unassigned unless a reliable structured source or a controlled company identity establishes the relationship.

GDELT is intentionally not included in this phase. Provider failure, HTTP 304, no new items, rate limiting and backoff are reported as distinct states. The default five-minute cadence is periodic collection, not a real-time news wire.
