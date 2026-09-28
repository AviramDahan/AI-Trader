# News recall policy

Approved news-only policy: portfolio/watchlist relevance >=0.55, universe
>=0.70, both medium/high materiality and neutral/positive/negative/mixed.
Market relevance >=0.40; directional sentiment is not required.

Canonical news supports a factual-title evidence path with an approved
observation, publication timestamp, valid source URL, recognized event, and
concrete factual wording. Stock titles must retain verified identity and the
existing primary-subject guard. Questions, speculative headlines and stock
listicles fail closed. Titles are already included in attributed model evidence;
no article body or missing context is invented. Independent quality review remains.

No historical requeue or replay. No dedupe/schema/trading changes. One analysis
job includes the existing analysis plus independent review (and bounded repair),
not necessarily one billable request. The existing global $25 budget gate and
personal-event queue priority remain. No additional AI benchmark is required.

Deployment uses the existing encrypted predeploy backup and readiness/rollback
mechanism. Compare new-event counts, analysis outcomes, delivery topics, actual
cost and duplicates from the deployment timestamp; absence of a naturally
qualifying event is not a Telegram E2E pass. No message-volume quota is enforced.
