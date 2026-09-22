# Forward-only legacy paper position management

The original scanner positions can be adopted only when their persisted executed
signal and structured tracking snapshot agree on symbol, quantity, entry and
execution time, and contain valid original stop and target levels.

Run `scripts/adopt_legacy_positions.py` without arguments to audit. Stop the local
backend using `scripts/stop-ai-trader.ps1`, then run it with `--apply` using the
project virtual environment. The script first creates a SQLite backup under
`.runtime/backups`, adds the schema, and adopts eligible positions atomically.
Restart with `scripts/start-ai-trader.ps1`. Repeated adoption is idempotent.

Adoption is not a new entry: it creates no entry fill or entry alert and does not
change cash or quantity. Management starts with completed five-minute bars after
adoption. Historical target/stop touches are not reconstructed. The first future
bar may legitimately close a position already beyond its original level.

Original position rows are preserved as quantity mirrors. Future exit proceeds
go to the original agent wallet, never to the new scanner account. Historical
entry costs are unknown. Legacy trades are explicitly marked, excluded from
verified strategy statistics, and do not create shadow trades. Original single
targets are preserved exactly. News monitoring starts at adoption and continues
while any quantity remains. Generic legacy trading cannot modify adopted rows.

The dashboard's Demo trades tab shows adopted trades and the separate legacy
wallet. Scanner status shows observed native lifecycle stages and cash/quantity
reconciliation. Legacy records and shadow executions cannot satisfy native live
verification. Zero signals or incomplete natural events remain pending; tests
must not insert synthetic signals into the active database or send test alerts.

The operational strategy remains single; staged exits remain shadow-only unless
explicitly selected. The local Windows backend, price monitor, news workers and
Ollama must remain running. This change does not migrate hosting to the cloud.
