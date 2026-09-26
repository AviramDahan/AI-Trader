"""One-shot, offline-only active portfolio transfer. Never opens the live DB writable.

Snapshots include authentication parent rows: treat them as secrets (0600).
Import only into an empty, migrated, isolated PostgreSQL database with workers off.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

TABLES = ("agents", "scanner_accounts", "positions", "signals", "scanner_signals",
          "scanner_orders", "scanner_trades", "scanner_fills", "scanner_legacy_adoptions",
          "scanner_target_revisions", "scanner_price_cursors", "scanner_operators")


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def export_data(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN")  # Consistent read snapshot; caller must stop writers for cutover.
    tables = {name: [] for name in TABLES}
    def select(table, where, args=()):
        rows = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}" WHERE {where}', args)]
        for row in rows:
            if row not in tables[table]:
                tables[table].append(row)
        return rows
    def ids(table, column, values):
        values = sorted({v for v in values if v is not None})
        if values:
            return select(table, f'"{column}" IN ({",".join("?" for _ in values)})', values)
        return []
    try:
        primary = select("agents", "name=?", ("us-stock-scanner",))
        if len(primary) != 1:
            raise ValueError("stable_scanner_identity_missing")
        agent = primary[0]["id"]
        trades = select("scanner_trades", "agent_id=? AND status='open'", (agent,))
        select("scanner_accounts", "agent_id=?", (agent,))
        select("scanner_operators", "agent_id=?", (agent,))
        ids("scanner_signals", "id", [t["signal_id"] for t in trades])
        fills = ids("scanner_fills", "trade_id", [t["id"] for t in trades])
        ids("scanner_orders", "id", [t["order_id"] for t in trades] + [f["order_id"] for f in fills])
        ids("scanner_legacy_adoptions", "trade_id", [t["id"] for t in trades])
        ids("scanner_target_revisions", "trade_id", [t["id"] for t in trades])
        ids("scanner_price_cursors", "ticker", [t["ticker"] for t in trades])
        positions = ids("positions", "id", [t.get("legacy_position_id") for t in trades])
        unmanaged = conn.execute("SELECT id FROM positions WHERE agent_id=? AND quantity>0", (agent,)).fetchall()
        if {r["id"] for r in unmanaged} - {r["id"] for r in positions}:
            raise ValueError("unmanaged_original_positions_require_review")
        ids("signals", "id", [s.get("external_signal_id") for s in tables["scanner_signals"]])
        # Include required original-schema parents, without unrelated histories.
        for _ in range(8):
            count = sum(map(len, tables.values()))
            for table in TABLES:
                for fk in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
                    target = fk["table"]
                    values = [r.get(fk["from"]) for r in tables[table]]
                    if any(v is not None for v in values):
                        if target not in tables:
                            raise ValueError("unsupported_parent_table:" + target)
                        ids(target, fk["to"], values)
            if count == sum(map(len, tables.values())):
                break
        settings = [dict(r) for r in conn.execute("SELECT * FROM scanner_settings WHERE key='active_exit_strategy'")]
        data = {"version":1, "created_at":datetime.now(timezone.utc).isoformat(),
                "tables":tables, "settings":settings, "primary_agent_id":agent}
        validate(data)
        data["snapshot_id"] = digest(data)
        return data
    finally:
        conn.close()


def validate(data):
    if data.get("version") != 1 or set(data["tables"]) != set(TABLES):
        raise ValueError("unsupported_snapshot_schema")
    if "snapshot_id" in data and data["snapshot_id"] != digest({k:v for k,v in data.items() if k != "snapshot_id"}):
        raise ValueError("snapshot_checksum_mismatch")
    tables = data["tables"]
    accounts = tables["scanner_accounts"]
    if len(accounts) != 1 or accounts[0]["agent_id"] != data["primary_agent_id"]:
        raise ValueError("missing_account")
    for field in ("cash", "initial_cash", "realized_pnl", "fees_paid"):
        if not math.isfinite(accounts[0][field]):
            raise ValueError("nonfinite_account")
    if any(t["status"] != "open" for t in tables["scanner_trades"]):
        raise ValueError("closed_trade_in_snapshot")
    if any(o["status"] in {"pending", "partial", "partially_filled"} for o in tables["scanner_orders"]):
        raise ValueError("active_order_requires_manual_review")
    for trade in tables["scanner_trades"]:
        for field in ("original_quantity", "remaining_quantity", "entry_price", "original_r", "current_stop"):
            if not math.isfinite(trade[field]) or trade[field] <= 0:
                raise ValueError("invalid_trade_numbers")
        if trade["remaining_quantity"] > trade["original_quantity"] + 1e-6:
            raise ValueError("quantity_exceeds_original")
        levels = [trade[f'tp{i}'] for i in (1,2,3)]
        percentages = [trade[f'tp{i}_pct'] for i in (1,2,3)]
        if not all(math.isfinite(v) and v > 0 for v in levels) or levels != sorted(levels):
            raise ValueError("invalid_preserved_targets")
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in percentages) or not math.isclose(sum(percentages),1,abs_tol=1e-5):
            raise ValueError("invalid_preserved_target_fractions")
        if trade['strategy'] not in {'single','staged'}:
            raise ValueError("unsupported_exit_strategy")
        if trade["side"] != "long" and trade["side"] != "BUY":
            raise ValueError("unsupported_short_position")
        json.loads(trade["settings_json"])
        fills = [f for f in tables["scanner_fills"] if f["trade_id"] == trade["id"]]
        if not trade.get("legacy_position_id"):
            entries = [f for f in fills if f["fill_type"] == "entry"]
            exits = [f for f in fills if f["fill_type"] in {"tp", "stop", "sell"}]
            pairs = [(sum(f["quantity"] for f in entries),trade["original_quantity"]),
                     (sum(f["quantity"] for f in entries)-sum(f["quantity"] for f in exits),trade["remaining_quantity"]),
                     (sum(f["fee"] for f in fills),trade["fees"]),
                     (sum(f["gross_pnl"] for f in exits),trade["realized_pnl"])]
            if not all(math.isclose(a,b,abs_tol=1e-5) for a,b in pairs):
                raise ValueError("fill_accounting_mismatch")
    return {table:len(rows) for table, rows in tables.items()}


def import_data(data, url, *, allow_defaults=False, scanner_token=None):
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from cloud_runtime import ROLE_KEYS
    validate(data)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        if conn.execute('SELECT max(version) version FROM schema_migrations').fetchone()['version'] != 2:
            raise ValueError('unsupported_destination_schema')
        for key in ROLE_KEYS.values():
            if not conn.execute("SELECT pg_try_advisory_xact_lock(719322,%s) AS ok", (key,)).fetchone()["ok"]:
                raise ValueError("workers_must_be_stopped")
        locked = [*TABLES, 'cloud_imports','scanner_news','scanner_candidates',
                  'scanner_telegram_outbox','scanner_settings','scanner_news_schedule']
        conn.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(
            sql.SQL(',').join(map(sql.Identifier, sorted(locked)))))
        if conn.execute("SELECT 1 FROM cloud_imports LIMIT 1").fetchone():
            raise ValueError("snapshot_already_imported")
        for table in TABLES:
            if conn.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))).fetchone():
                raise ValueError("destination_not_empty:" + table)
        # Reject non-empty pending queues/history rather than merge two systems.
        for table in ("scanner_news", "scanner_candidates", "scanner_telegram_outbox", "scanner_settings"):
            if conn.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(sql.Identifier(table))).fetchone():
                raise ValueError("destination_not_clean:" + table)
        for table in TABLES:
            for row in data["tables"][table]:
                conn.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, row)),
                    sql.SQL(",").join(sql.Placeholder() for _ in row)), list(row.values()))
            # Identity sequence must advance past preserved identifiers.
            if data["tables"][table] and "id" in data["tables"][table][0]:
                sequence = conn.execute("SELECT pg_get_serial_sequence(%s,'id') AS seq", (table,)).fetchone()["seq"]
                if sequence:
                    conn.execute("SELECT setval(%s,%s,true)", (sequence,max(r["id"] for r in data["tables"][table])))
        for setting in data["settings"]:
            conn.execute("INSERT INTO scanner_settings(key,value_json,updated_at) VALUES(%s,%s,%s)",
                         (setting["key"],setting["value_json"],setting["updated_at"]))
        # Carry current cash unchanged. Record the omitted history as an explicit
        # opening audit balance, NOT fabricated fills or closed trade performance.
        main_ids = {t["id"] for t in data["tables"]["scanner_trades"] if not t["is_shadow"] and not t.get("legacy_position_id")}
        cash_flow = sum(((-1 if f["fill_type"] == "entry" else 1)*f["quantity"]*f["price"]-f["fee"])
                        for f in data["tables"]["scanner_fills"] if f["trade_id"] in main_ids and f["fill_type"] in {"entry","tp","stop","sell"})
        account = data["tables"]["scanner_accounts"][0]
        baseline = {"cash_adjustment":account["cash"]-account["initial_cash"]-cash_flow,
                    "snapshot_id":data["snapshot_id"],"historical_performance_not_imported":True}
        conn.execute("INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('active_snapshot_baseline',%s,%s)",
                     (json.dumps(baseline),data["created_at"]))
        # Fresh news review is scheduled; no old news, outbox or duplicate-alert state.
        tickers = {t["ticker"] for t in data["tables"]["scanner_trades"] if not t["is_shadow"]}
        for ticker in tickers:
            conn.execute("INSERT INTO scanner_news_schedule(ticker,next_due_at,status) VALUES(%s,%s,'due')", (ticker,data["created_at"]))
        # Read back every preserved field before committing. No accounting mutation.
        for table in TABLES:
            actual = conn.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))).fetchall()
            original = data["tables"][table]
            if allow_defaults and original:
                columns = set(original[0])
                if any(set(row) != columns for row in original):
                    raise ValueError('inconsistent_recovery_columns:' + table)
                actual = [{key: row[key] for key in columns} for row in actual]
            if sorted(map(digest,actual)) != sorted(map(digest,original)):
                raise ValueError("roundtrip_mismatch:" + table)
        if scanner_token is not None:
            if not allow_defaults or len(scanner_token) < 32:
                raise ValueError('invalid_recovery_scanner_token')
            conn.execute('UPDATE agents SET token=%s WHERE id=%s', (scanner_token,data['primary_agent_id']))
        conn.execute("INSERT INTO cloud_imports(snapshot_id,manifest) VALUES(%s,%s)",
                     (data["snapshot_id"],json.dumps({"counts":validate(data),"baseline":baseline})))
    return validate(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export","validate","import"])
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--source")
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args()
    if args.action != "validate" and not args.writers_stopped:
        parser.error("Explicit --writers-stopped acknowledgement required")
    if args.action == "export":
        data = export_data(args.source)
        fd = os.open(args.snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            if os.name == 'nt':
                principal = os.environ.get('USERDOMAIN','') + '\\' + os.environ['USERNAME']
                subprocess.run(['icacls',str(Path(args.snapshot).resolve()),'/inheritance:r',
                                '/grant:r',principal+':(F)'],capture_output=True,check=True)
            json.dump(data,out,ensure_ascii=True,allow_nan=False)
        print(json.dumps(validate(data)))  # Counts only, never parent-row tokens.
    else:
        data = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
        if args.action == "validate":
            print(json.dumps(validate(data)))
        else:
            from config import DATABASE_URL
            print(json.dumps(import_data(data,DATABASE_URL)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Database validation exceptions can contain complete parent rows/tokens.
        print('Active snapshot operation failed: '+type(exc).__name__,file=sys.stderr)
        sys.exit(1)
