-- No historical rewrite. V2 has one real target; unused legacy slots are NULL.
ALTER TABLE scanner_signals ALTER COLUMN tp2 DROP NOT NULL;
ALTER TABLE scanner_signals ALTER COLUMN tp3 DROP NOT NULL;
ALTER TABLE scanner_signals ALTER COLUMN rr2 DROP NOT NULL;
ALTER TABLE scanner_signals ALTER COLUMN rr3 DROP NOT NULL;
ALTER TABLE scanner_trades ALTER COLUMN tp2 DROP NOT NULL;
ALTER TABLE scanner_trades ALTER COLUMN tp3 DROP NOT NULL;
ALTER TABLE scanner_orders ADD COLUMN IF NOT EXISTS plan_json TEXT NOT NULL DEFAULT '{}';
