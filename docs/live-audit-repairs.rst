Live audit corrective batch -- review only
=========================================

Scope
-----
Based on the 12 October audit, this batch corrects diagnostics, retained decision
explanations and public rendering. No merge/deploy, production migration, trading
parameter change or live test action is authorized by this implementation task.
It does not guarantee entries, profitability, SEC catch-up or provider access.

Changes
-------
* Breakout rejections have explicit target-stage classification and Hebrew
  labels. The actual admission guards, minimum RR and AI filters are unchanged.
* Research distinguishes configured SEC mode from a retained snapshot plus
  evidence IDs, and distinguishes retained evidence from a PAPER ranking effect.
  Current provider health is not used to reinterpret historical decisions.
* A bounded public explanation from the existing validated AI reason is saved
  prospectively, sanitized at write and read, and displayed as untrusted model
  opinion with an uncalibrated score. No prompts, chain of thought, second AI
  call or historical explanations are reconstructed. Sensitive explanations
  are omitted, rather than partially rewritten and presented as the original.
* SEC discovery records safe phase/issuer/error/retry metadata in its existing
  offset JSON and keeps exact known errors in checkpoints. The permission-gated
  status endpoint exposes bounded failure details and oldest pending first-seen
  time. Queue, worker cadence, document limits and shared request throttle stay.
* Invalid or cross-issuer continuation filenames cannot be silently skipped;
  unexpected 304 cannot complete unfinished catch-up; unknown acceptance dates
  cannot masquerade as the initial 90-day discovery horizon. Checkpoint errors
  retain the prior page/accession. Retry deduplicates already retained filings.
  These defects were reproduced with fixtures; they are not claimed to be the
  unexplained production JPM failure's root cause.
* Short daily histories are diagnosed separately from empty provider responses
  and invalid shapes. The 65-completed-bar technical requirement is unchanged;
  short frames are NOT cached/admitted and predecessor histories are not spliced.
  Metadata is bounded to 50 displayed symbols. Existing cache timestamps/data
  and the whole-scan coverage/fail-closed rules remain unchanged.
* Public news cleanup covers the observed WSJ attribution wrapper and duplicated
  relay phrase. It is idempotent and preserves subjects, uncertainty and mandatory
  license credits. Stored evidence, AI inputs, routing and outbox keys are intact.
* Existing LONG TP-on-touch slippage is documented in results and asserted in
  the full lifecycle test. No execution formula, stored target/stop or fill is
  changed. A floor-protected TP would be a separate future contract decision.

Still not verified or externally dependent
------------------------------------------
JPM's old checkpoint stores only ValueError. This batch supplies safe diagnosis
for subsequent NORMAL attempts; it does not guess or mass-replay those records.
GlobeNewswire HTTP 403 is still an access dependency. No alternate IP, article
scraping, terminal-state reset, unauthorized endpoint or rights bypass is added.
The collector remains visibly degraded until legitimate natural recovery.

VYLR's issuer and recent listing are documented in official SEC filings:
https://www.sec.gov/Archives/edgar/data/2128626/000119312526409909/d115079d8k.htm
Its regular-way trading was expected to start 1 October 2026. The absence of
65 post-listing completed sessions is not a mapping error to solve by inventing
history. The exact latest Yahoo response is NOT verified by this fixture batch;
future normal download diagnostics distinguish short history from no response.
There is no ticker-specific rule, news bonus, artificial price or technical bypass.

Verification
------------
Synthetic, controlled-clock regressions first reproduced nine audit failures.
An additional missing-timestamp continuation test separately reproduced premature
catch-up completion. All use isolated databases and mocked providers/AI.
Tests cover unknown/error state, safe model text, HTML escaping, publisher subjects,
required credits, restart/dedupe, short-history fail-closed behavior and unchanged
cache timestamps. PostgreSQL versions exercise the same application code.

Run on the final source revision:
python -m pytest service/server/tests -q
python -m pytest service/server/tests_pg -q
Frontend: npm ci; npm run test:research; npm run test:activity; npm run build.
Cloud Readiness additionally builds a Linux image and runs the real encrypted
backup/restore and bounded backup-health suites. A skipped compatibility-image
workflow is NOT proof that a compatibility test ran; this batch changes no
schema, plan serialization, backup format or trading reader contract.

The optional RESEARCH_PREVIEW_HTML test argument renders real components and CSS
with synthetic records only for disposable browser visual QA. It does not start
an application worker, execute UI effects, contact Production or send Telegram.

Release and rollback, not executed
---------------------------------
Use the existing main-only release gate after explicit release authorization and
passing checks on the exact merge SHA. Reverify sole workers, schema 7, accounting,
holds/reservation, encrypted backup and the actual retained image before replacing
services. No schema migration or new backup-format version is required.
Older readers still understand the offset field and ignore additive JSON fields.
No order/trade/fill schema, execution plan or accounting record changes.
Rollback is a compatible binary on the CURRENT database, not a database rewind.

After an authorized deployment, observe natural scans: corrected stage/labels,
real retained evidence states, prospective reasons, SEC checkpoint/retry progress,
history gap diagnostics, healthy monitor and queues. Validate naturally generated
backups and read actual messages only when natural events occur. No replay/test
trade/message, lowered threshold, provider probe or new automation is implied.
New native entry-to-exit E2E remains WAITING_FOR_NATURAL_EVENT until actually linked.
