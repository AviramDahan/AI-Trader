News delivery assurance and agent acceptance
===========================================

Purpose and ownership
---------------------

Collector availability, completed analysis, editorial quality and delivery are
separate results. A healthy container, successful poll, or empty runnable queue
does not prove that usable news reaches a destination. No publication quota is
introduced. Rejection can be correct and a quiet source is not automatically
broken.

Within an explicitly requested existing team run, the coordinator assigns:

* Data: source availability, classification, verified issuer identity and the
  earliest observed admission failure. Distinguish unavailable from empty.
* UI/Telegram: approved routes, pending/retry/sent notices, current-version
  linkage and bounded destination readback when separately authorized.
* AI: actual retained analysis/review outcomes, not synthetic live requests or
  invocation counts mistaken for unique events.
* Independent QA: reproduce the defect before the fix; challenge false positives,
  stale/missing evidence, restarts and downstream safety on synthetic fixtures.
* Coordinator: compare the same dated cohort with the previous dated receipt,
  maintain issue ownership, and avoid a functional PASS from process health.

Roles are responsibilities, not a requirement to spawn one agent per role. Reuse
the existing specialists, at most three beside the coordinator, with exclusive
file ownership. Do not mark unperformed responsibilities completed. The reviewer
must execute independent controls against the actual patch, not only read an
implementer's passing count.

Required evidence before closing a news finding
---------------------------------------------

1. Pin the actual installed build, observation time, UTC half-open window and
   coverage limits. Do not copy a previous release's success as current proof.
2. Measure unique newly created canonical events, reason buckets, current-version
   completed/failed analyses, routed events and actually sent linked events.
   Count each event once per stage; do not add overlapping provider memberships,
   revisions, repeated polls, AI attempts or Telegram multipart presentations.
3. Keep notices sent during the window separate from the new-event cohort.
   An older event sent now cannot prove the new cohort passed. Trump relay and
   separate SEC intelligence notices cannot mask stalled canonical news.
4. Inspect a bounded sample of the dominant rejection categories. A high identity
   failure rate is a review trigger, not evidence that all failures are bugs.
   For macro stories, a missing company identifier is not itself appropriate;
   for company stories, a related ticker or common word is not verified identity.
5. Record fingerprint, owner, dated evidence, impact, reproduction, status and
   closure condition. Known source failures remain open until the relevant
   evidence changes. Repeatedly reporting an outage is not remediation.
6. Keep engineering regression success separate from natural publication proof.
   An isolated patch/green CI is not an installed fix. After an approved release,
   missing natural events stay WAITING_FOR_NATURAL_EVENT. Do not generate,
   replay, requeue or publish old stories to manufacture a successful check.

Continuous retained evidence, without new jobs
----------------------------------------------

``news_events.funnel_health.snapshot`` is called by the existing cloud watchdog.
It uses a fresh repeatable-read READ ONLY PostgreSQL transaction with five-second
statement and two-second lock timeouts. Aggregates cover at most six hours and
never materialize all history, article bodies or per-event reports. Observation
failure, invalid metadata or stale retained evidence is UNKNOWN, not zero.

Two operational advisories request human/agent investigation:

* At least50 new events, oldest at least one hour, at least80% currently blocked
  for identity/insufficient information, and none routed on the current version.
* At least50 new events, oldest at least three hours, and no canonical notice
  sent during the observation window.

These are monitoring heuristics, not trading/news eligibility thresholds, proof
of a bug, an AI budget increase, or a required volume of articles. The existing
four-hour private Admin report includes the funnel. The private system-status
projection displays fresh bounded counters and marks required review separately
from provider outages. It does not enqueue public news or initiate source/AI
calls. Advisories NEVER invoke the safety failback, relax rights/freshness/
identity/materiality/quality/dedupe gates, or alter trading state.

Respect the human's scheduling state
-----------------------------------

Codex team automations may be paused independently of cloud service monitoring.
An agent report is a dated work receipt, not continuously employed background
workers. Do not reactivate paused Codex messages, add timers, create new chats or
claim autonomous agent supervision without a real permitted dispatch. Existing
cloud observations continue under their own service lifecycle. Merge, deployment
and Production settings require their applicable explicit release authority.

Regression acceptance
---------------------

Fixtures must include factual sovereign rate decisions and negative company/
preview/opinion examples; current-version versus older analysis; event versus
window delivery; unrelated Trump/SEC traffic; quiet/no-input and unavailable
states; invalid counters; source redirects, single-use persisted recovery and
restart/backoff/crash behavior. Preserve Baseline and strategy admission, risk,
TP/SL, exposures, provider/model/budget choices and existing public destinations.
