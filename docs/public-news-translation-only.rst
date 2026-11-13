Public general news: translation only
=====================================

``STOCK_SCANNER_PUBLIC_TRANSLATION_ONLY_ENABLED`` defaults to false. When enabled,
general public news without a verified ticker, signal or position is translated
from source facts, independently checked for fidelity and Hebrew, and deduplicated
against published evidence. The message has no trader interpretation. Untranslated,
unsupported or unreliable content is not published. Existing provider, timestamp,
source licensing, cutover, conflict, freshness and duplicate controls still apply.

This is a deliberate editorial policy change: public general-news publication no
longer uses the model's topical relevance, impact, sentiment or materiality scores.
The result stores these unmeasured fields as NULL, not fabricated scores. This can
increase routine or irrelevant news; factual translation review is not an importance
filter. Existing stock, watchlist, open-position and trading decision routes retain
their full analysis, identity, news, AI, risk, exposure and execution controls.

Both legacy and canonical publisher paths implement the mode. Legacy revalidates
the item's scope under its write transaction; an item that gains a ticker or signal
is requeued for the trading analyzer. Canonical revalidates source version, current
identity, eligibility and enabled mode before send. New facts remain separate from
duplicates. Restoring the flag to false stops new translation-only processing;
already queued legacy translation messages are not automatically cancelled.

The mode still uses AI for translation, an independent factual/Hebrew review, and
where necessary comparison with prior news. It is not zero AI calls or a guarantee
of lower latency. The existing local inference gateway, model, provider, budgets,
backoff, user positions and output/context limits are unchanged. A model running
on CPU can still time out. No replay or test message is needed for rollout proof;
observe natural new messages and record a lack of events as waiting, not success.

Integrated local failure recovery
---------------------------------

Public translation and its independent review participate in the same exact-stage
checkpoint mechanism as news analysis. A successful translation is reused after a
later review transport failure, including after a process restart. Source version,
prompt, draft, schema, model and output budget remain part of the cache identity;
invalid output is rejected, never rescaled or stored as a valid stage. A cached
result creates no new inference usage row.

Local translation failures within the publication job also advance the existing
news circuit. An intermediate valid stage does not reset that circuit; only a
completed story containing a live validated stage does. Unrelated translation and
position tasks cannot change it. These changes affect no shared gateway limits,
Windows settings, trading analysis, provider fallback or publication fidelity
requirements. Offline mocked failures prove resumption behaviour, not sustained
real-model reliability. The feature remains OFF until an authorized release.
