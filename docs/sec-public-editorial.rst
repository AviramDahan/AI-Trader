Public SEC editorial selection
=============================

Scope
-----

This change affects only the deterministic public ``sec_intelligence`` notice.
It is not a parser, company-facts, decision-snapshot, research-weight, ranking,
trading, provider-access or general-news policy change. It adds no model call.
Existing paper/topic/cutover/freshness/issuer/correction/accession-dedupe/outbox
guards remain in place. Form4 purchase eligibility and wording, and the existing
exclusion of unquantified8-K text from this particular topic, remain unchanged.
The separate canonical news pipeline is not this formatter.

What changed
------------

Previously the single largest numeric ``abs(percent_or_percentage_points)``
won, even when it described an older comparative period or tiny debt balance.
The message omitted the periods and amounts needed to interpret that percentage.
The percentages could be arithmetically correct and still give a misleading
impression of what changed in the newly accepted filing.

The public selector now:

* Selects the latest retained period separately for a metric and compatible
  duration (quarter, annual or instant balance), BEFORE applying the unchanged
  material-change controls. An immaterial or uncomparable latest period cannot
  revive an older material period in the same group.
* Keeps quarter and annual durations separate; unsupported YTD comparisons are
  not guessed or substituted. One most-recent usable period is displayed per
  metric. Conflicting same-period alias values are omitted, including a current
  value whose alias lacks a prior comparison. Missing dates, unit/concept basis,
  nonfinite values and incompatible prior periods are not invented.
* Prefers up to three readable operating facts in a fixed order: revenue,
  operating income, operating cash flow, operating margin. Percentage magnitude
  is not an importance score and percentages are not ranked against margin pp.
* Allows cash/current-debt/long-term-debt only as secondary context when a
  material operating-cash-flow fact is actually displayed with matching current
  AND prior period ends. These balances never create a notice by themselves or
  displace the three operating facts. Their presence establishes neither a cause
  of the change nor an improvement/deterioration in liquidity or solvency.
* Shows current/prior reported values, explicit USD or percent units and exact
  current/prior periods. Balances are labelled ``ליום``; flows are date ranges.
  Margin changes use percentage points. Positive-base transitions into a negative
  result retain their signs; zero/negative-base growth is not asserted.
* Adds one compact definition of the measured metric, not a causal business
  story or forecast: revenue describes reported revenue scope; operating income
  describes the reported operating result; margin is operating income relative
  to revenue; operating cash flow is money generated/used in operations rather
  than the cash balance. No stock reaction or liquidity conclusion is invented.

For example, a synthetic2026 quarterly revenue120 versus100 (20%) is displayed
instead of its2025 comparative100 versus25 (300%). A synthetic debt balance
moving1000 to3000 cannot replace billion-scale revenue merely because200% is
larger. These examples are not observations about an actual issuer.

Evidence and limits
-------------------

``latest`` means latest supported period in the already retained comparison
payload, not independently verified coverage of every period in a complete filing.
The existing parser's bounded ``current[:4]``/``result[:40]`` output is unchanged.
Missing data is not reconstructed with another fetch or a model. Source facts,
original filing times and immutable historical decision evidence remain intact.
The acceptance date displayed by the notice is distinct from the accounting
period, which is now separately explicit.

Only new natural processing produces the new copy. Already queued/sent notices,
past facts and public eligibility decisions are not rewritten or replayed.
No claim is made that all actual prior issuer notices selected an old period,
that more publication is always useful, or that this change opens positions.

Telegram reading layout
-----------------------

Each selected financial metric has its own short block: metric name, current
full reported amount and unit, exact current period, previous amount and unit,
exact comparison period, rounded change, then the existing one-line metric
definition. Blank lines separate the at-most-three facts. A balance uses its
``ליום`` date rather than a flow range. A margin keeps percentage units and a
percentage-point change, not USD or percentage growth. Different metrics keep
their own dates; no common period, fiscal-quarter name or business cause is
inferred from a calendar range.

Full amounts and signs remain unabridged. The existing one-decimal displayed
change now says ``כ־`` to make its rounding explicit; the retained change and
the unchanged materiality threshold are not rounded or recalculated for
selection. No directional arrows or visual string reversal are introduced.
The existing final Telegram boundary still applies its ordinary bidi handling.

The footer ``נקלט ב־SEC`` labels the same retained ``accepted_at`` value already
used by this notice. It is not the accounting period, processing time, outbox
creation time or Telegram delivery time. This presentation-only update affects
newly created copy, not existing queued/sent notices. It changes neither
selection nor a source's factual accuracy and does not repair historical text.

Verification
------------

Synthetic tests invoke the real formatter, parser-shaped facts and actual
``process_jobs``/transactional outbox code with mocked SEC transport. Disposable
SQLite and the existing isolated PostgreSQL ``test_*`` fixture cover evidence
preservation, silence for unavailable comparisons, correction labelling,
freshness and accession dedupe. PostgreSQL cases are explicitly unverified when
``TEST_POSTGRES_URL`` is absent; skipped cases are not a live/Production PASS.
No provider, model, Telegram or production database is contacted by the tests.
