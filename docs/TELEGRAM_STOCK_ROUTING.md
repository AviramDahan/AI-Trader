# Telegram stock-news routing

Implemented 2026-09-25. Public allowlisted channel messages now receive conservative
stock identity matching during ingestion, before scope, job priority and AI review
are selected. This closes the former all-Telegram-posts-are-market-only gap.

## Identity evidence

The allowlist of known equities is the existing local cached stock universe plus
stock identities already present in trades, signals and the news watchlist.
No market-data call or LLM call is added to ingestion. Compiled patterns are cached.

Accepted evidence is an explicit uppercase cashtag (`$INTC`), exchange-qualified
symbol (`NASDAQ:INTC`), full multiword company identity, or a reviewed distinctive
company alias. Exact word boundaries are required. URLs and @channel signatures
are excluded. Common words such as Apple, Meta, Strategy and Target are not
accepted as single-word aliases; people/sector mentions are not inferred as stocks.
Evidence is saved in source_facts_json.ticker_evidence for new records.

Matching proves an identity is mentioned, **not** that a story materially affects
that equity. The existing strict AI relevance/materiality checks remain in place.
Unknown/unverified mentions remain market news; coverage is deliberately incomplete.

## Destinations and safety

- Verified open-position news: position_news -> personal/watchlist topic.
- Verified watched-stock news: watchlist_news -> personal/watchlist topic.
- Other verified stock news: stock_news -> important-stocks topic, only with high
  materiality and the existing strict relevance threshold.
- No verified equity identity: existing general market-news pipeline.

Same-stock open-position and watchlist alerts are not doubled. Cross-source and
repeated-message deduplication remain active. Multiple distinct affected stocks
may legitimately have separate personal assessments. An assigned stock story
does not also generate a general-market bulletin. No trading state is changed.
No historical replay or relaxation of filters accompanied this deployment.

## Validation

Isolated tests cover explicit symbols, reviewed names, ambiguous words, people,
URLs, unknown symbols, production-shaped Telegram ingestion -> verified identities
-> open-trade links -> AI decision -> persistent outbox -> mocked Bot API topic
650/477 payloads, duplicate ingestion and unchanged paper positions.
All mocked provider data lives in temporary test databases; no synthetic Telegram
messages are sent. Tests do not imply that a new naturally qualifying story was
delivered to both live topics during the verification window.
