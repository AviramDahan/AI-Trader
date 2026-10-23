Trump translation preparation diagnostics
=========================================

Scope
-----

This is forward-only, private diagnostic evidence for the existing bounded
Hebrew preparation. It does not make a translation more accurate, generate a
missing caption, repeat a past send, increase the two-attempt budget, or change
providers, models, output/context limits, flags, leases, retries or publication
eligibility. Hebrew/source text and exception text are never stored here.

The original translation cache and bilingual/media receipt formats are unchanged.
Already published history is not reconstructed. In particular, an older
``unavailable`` cache does not reveal whether the failure was readiness,
transport, capacity, schema, grounding, editor rejection or a crashed attempt.
Such an older cause remains unknown.

Private evidence contract
-------------------------

``scanner_settings`` may contain one ``trump_translation_diagnostic_v1:<rowid>``
record. Its exact fields are version, source binding, canonical cache SHA256,
attempt, cache status, fixed category and aware UTC recorded_at. The pure
``checked_diagnostic`` validator requires the exact current source/cache binding,
an actual integer attempt, the unchanged cache schema/status and a nonfuture
timestamp. Missing, substituted, unknown-field or restored evidence is not proof.
The row identifier is internal and is not a public chat/user/source identifier.

The record is written in the existing short preparation transactions. A working
marker is committed before the optional inference callback. It means only that
an attempt was reserved: it does NOT prove that a request was sent, inference
completed or content was accepted. A failed first attempt may retain its fixed
category while the existing cache remains ``working`` and waits for its existing
retry. Reserving the next attempt resets its category to unknown. Exhaustion
after a crash therefore cannot pretend that the previous rejection caused the
final unavailable state.

The fixed categories distinguish unknown, local unavailable, context capacity,
transport failure, schema invalid, not grounded, editor rejected and preparation
revoked. Successful translation uses ``none``; an actual empty/link/media source
uses ``source_text_absent``. Typed capacity or transport categories describe the
observed exception class, not an independently verified provider/root cause.
Unknown exceptions retain neither their string nor their arguments.

This optional record is never consumed for queue ownership, preparation budgets,
cache acceptance, rendering, sending, ACK/retry or recovery decisions. Reusing an
old terminal cache creates no diagnostic. Stale/revoked work cannot publish a
terminal diagnostic or overwrite the accepted cache. Generic sender cleanup of
``outbox.last_error`` cannot erase this separate preparation evidence.

Compatibility and limits
------------------------

Old readers ignore the new settings namespace. The active-state exporters still
select only ``active_exit_strategy`` and ``paper_entry_emergency_v1``; this
diagnostic is not newly added to encrypted active snapshots and does not require
a new recovery/cache/receipt format. After a restore, missing preparation
diagnostics remain not retained rather than being regenerated. Other analytical
history/private-cache retention limits remain unchanged.

Synthetic tests execute the actual preparation/cache/lease path with local
callbacks and disposable SQLite. They cover known rejection, schema failure,
unknown/private errors, marker-before-callback, empty media source, stale/revoked
work, old-terminal cache reuse, crash exhaustion and strict diagnostic binding.
No provider, AI inference, Telegram, Production mutation or historical replay is
used to create acceptance evidence. Exact-source CI and relevant PostgreSQL
regressions remain release gates, not a claim made by this document.
