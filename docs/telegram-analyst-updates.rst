Analyst updates topic
=====================

``TELEGRAM_ANALYST_UPDATES_TOPIC_ENABLED`` defaults OFF. When explicitly enabled,
actual equity rating upgrades/downgrades, coverage initiations with a rating,
and price-target raises/cuts in regular broad news use only
``TELEGRAM_ANALYST_UPDATES_THREAD_ID``. A missing dedicated target fails closed.
There are no extra AI calls, posts, subscriptions, or trading changes.

Classification is deterministic against the retained original headline and
limited original context. Canonical evidence must carry the exact current
event headline; an unrelated attached source cannot lend its analyst label.
A clear analyst action is required. Static targets,
speculative future actions, trade plans, product/software upgrades and credit
ratings do not qualify. Source categories/hints alone are insufficient. At
outbox dispatch the exact legacy content/audit version or canonical current
event/analysis/epoch must match; model interpretation cannot invent an action.
Legacy versions accept only the producer's known 20-hex source version,
64-hex enriched evidence version, or explicit v1, with exact audit-first hash
matching. Stock audiences must be valid sorted unique verified symbols.
``Adjusts PT`` requires explicit monetary to/from values that differ; a static
maintained recommendation is not invented into a new rating change.
Direct news sender calls may classify a clear factual headline, while retained
dispatch supplies its source decision explicitly.

Coverage is deliberately conservative. A headline such as ``Morgan Stanley
Downgrades Cisco On AI Impacting Gross Margins`` with no explicit stock rating
or supporting excerpt is not inferred into a rating change. It remains an
unclassified source, subject to the public quality policy; this implementation
does not claim every possible analyst headline is covered.

Reports retain precedence. SEC intelligence, Trump, signals, trades, status
cards and the weekly calendar keep their destinations. Held/watchlist news
retains its personal ticker audience; broad analyst coverage converges in the
dedicated topic. Exact source/version duplicate broad routes coalesce under
the existing sole-publisher dispatch lease, including uncertain prior sends.
Different multi-company ticker subsets and personal audiences are preserved.

Durable original event types and keys are never rewritten. Canonical general
publication keys bind the actual analyst destination at preparation and send,
independently of the directional-news flag. Existing prepared keys that no
longer match are cancelled, never rewritten/replayed. Source rights, current
membership, freshness, cutover epochs and ordinary report guards run first.

Tests use synthetic sources, disposable SQLite and mocked HTTP. They prove
routing, version/epoch guards, report precedence, missing-target failure,
restart/dedupe behavior and canonical destination identity only. Live delivery
and ongoing source coverage require natural evidence after operator rollout.
