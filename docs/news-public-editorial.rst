Public news: impact and conservative release consolidation
=========================================================

Scope
-----

This is a public-channel editorial change, not a trading policy or a promise
of more messages. MARKET still accepts topical low-materiality analysis as a
valid result, but public routing now requires medium/high materiality as company
news already did. Numerical relevance thresholds remain 0.30/0.55/0.70.
Company/legacy schemas, scanner signal-news inputs, trading news guards and all
execution controls stay unchanged. Sent messages are not edited or replayed.

The MARKET analysis and independent editorial reviewer receive a source-bound
importance rubric: a concrete change, its time/period, available comparison,
and identifiable economic/business significance. Percentage size, dramatic
wording and topical relevance alone do not establish impact. No consensus,
causality, surprise or expected price move may be fabricated. Existing bilingual,
number, unsupported-claim, license, freshness and conflict checks remain required.
No schema, model, provider, retry allowance or AI budget changes are introduced.
Normal canonical analysis remains two calls; the existing single shared repair
allowance and failure behavior remain unchanged.

Within the existing oldest-20 pending-job window, position/watchlist preference
remains first, then concrete event types/reported macro facts before generic
updates, with stable oldest-first ties. This is scheduling preference, NOT an
impact score, publication authorization, new queue or additional model quota.

Exact release identity and updates
----------------------------------

Existing exact URLs, SEC accessions, substantive verbatim evidence and qualified
wire syndication anchors remain. No fuzzy title, same-ticker/day, numeric
similarity, country-only or generic headline merge is added.

An additional bounded identity supports complete CPI bulletins, for example::

  New Zealand CPI (Q/Q) Q3: 0.7% (est 0.8%; prev 1.5%)
  New Zealand CPI (Y/Y) Q3: 3.7% (est 3.8%; prev 4.1%)

Required: allowlisted explicit country, CPI vs Core CPI series, Q/Q, M/M or
Y/Y component, explicit quarter/month (optional explicit reported year), actual,
forecast and previous percentages, approved rights, and no company identity/CIK/
ticker. Country + series + reported period/year-presence + source UTC publication
day identify the release. Q/Q is quarterly, M/M monthly; annual comparisons
belong only to the same explicit quarter/month release. Publication day NEVER
supplies a missing reported year/period. Preliminary/final/revised prose and
unknown formats do not receive this anchor.

``news_events.editorial.macro_release`` supplies verbatim-grounded claims keyed
by release, component and actual/forecast/previous role. A new annual component
is a new fact in the SAME event, not a second unrelated story. Every original
source, URL and version remains retained; analysis receives their union. Each
new material version still passes analysis, quality, routing and send-time gates.
Conflicting same-component values from active sources remain contested and
blocked, not overwritten. A same-provider/item revision retains its old row and
uses only the newest active revision, as before; this is not a second source.
Provider claims cannot overwrite the reserved deterministic claim namespace.
Unknown extra prose is retained and, absent structured proof of a new fact,
uses the existing ``needs_material_review`` hold rather than silent deletion or
automatic publication. A bridge to two existing events is quarantined, never
used to merge their publication histories.

Coverage limitation: ``NEW ZEALAND CPI QOQ ACTUAL ...`` without an explicit
quarter/month cannot safely be equated with Q3. It stays on the existing path.
This fix does NOT solve every overlap or invent the observed headline's period.
Natural-source coverage and quality after release must be measured separately;
synthetic tests are not live publication quality or profitability evidence.

Recovery and release
--------------------

No migration, backup format, deployment helper or new feature flag is needed.
Reingesting a seen source adds supported anchors but does not claim a new AI job
or rewrite old analyses. Restart retains canonical IDs, evidence, versions,
outbox dedupe and current-version send-time checks. Stale versions, withdrawals,
licensing and conflicts still cannot send. No historical replay, public test
messages, provider calls or paid AI calls are needed for validation. The isolated
branch requires explicit release approval before this is active in Production.
