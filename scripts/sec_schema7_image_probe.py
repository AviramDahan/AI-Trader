"""Synthetic PostgreSQL/age proof using complete, unmodified application images.

Only the clock and external transports are mocked. No application module is
mounted over an image, and no worker, provider, Telegram or paid AI is started.
The workflow uploads only filtered summaries, never the temporary age identity.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests
import cloud_runtime as cloud
import database
import scanner_engine as engine

assert os.environ.get("AI_TRADER_CLOUD") == "true"
assert os.environ["DATABASE_URL"].startswith("postgresql://isolated:")
assert os.environ.get("SEC_INTELLIGENCE_MODE") == "off"
assert not os.environ.get("OPENROUTER_API_KEY")
assert not os.environ.get("TELEGRAM_BOT_TOKEN")
ROOT = Path("/proof")
AT = "2026-09-28T13:30:00Z"
BAR = dict(at="2026-09-28T13:35:00Z", open=100, high=101, low=99.5, close=100)


def schema():
    with database.get_db_connection() as conn:
        return conn.execute("SELECT MAX(version) n FROM schema_migrations").fetchone()["n"]


def state():
    with database.get_db_connection() as conn:
        result = {key: [dict(row) for row in conn.execute(query)] for key, query in {
            "accounts": "SELECT id,agent_id,cash,fees_paid,realized_pnl FROM scanner_accounts ORDER BY id",
            "legacy_wallet": "SELECT id,cash FROM agents ORDER BY id",
            "legacy_positions": "SELECT id,quantity,entry_price FROM positions ORDER BY id",
            "trades": "SELECT id,signal_id,order_id,is_shadow,status,remaining_quantity,fees,realized_pnl,current_stop FROM scanner_trades ORDER BY id",
            "fills": "SELECT id,trade_id,order_id,quantity,price,fee FROM scanner_fills ORDER BY id",
            "holds": "SELECT id,status,signal_id,limit_price,quantity,valid_until,plan_json FROM scanner_orders WHERE status='recovery_uncertain' ORDER BY id",
            "reserved": "SELECT COALESCE(SUM(limit_price*quantity),0) amount FROM scanner_orders WHERE status IN ('pending','recovery_uncertain') AND purpose='entry'",
        }.items()}
        result["plans"] = [dict(id=row["id"], plan=json.loads(row["settings_json"]).get("target_plan"))
                           for row in conn.execute("SELECT id,settings_json FROM scanner_trades ORDER BY id")]
        return result


def save(name):
    (ROOT / (name + ".json")).write_text(json.dumps(state(), sort_keys=True))


def unchanged(name):
    assert state() == json.loads((ROOT / (name + ".json")).read_text()), name


def accounting():
    assert engine.dashboard_payload()["lifecycle_verification"]["accounting_ok"]


def leases():
    for role in cloud.ROLE_KEYS:
        owner = cloud.RoleLease(role)
        try:
            try:
                cloud.RoleLease(role)
            except RuntimeError as exc:
                assert "role_already_owned" in str(exc)
            else:
                raise AssertionError("duplicate_role_acquired")
        finally:
            owner.close()


def record(ticker, plan=None):
    signal = dict(ticker=ticker, company="Synthetic Company", action="BUY", entry=100,
                  stop_loss=plan["stop"] if plan else 97, confidence=.91,
                  time_horizon="weeks", reason="synthetic", relevant_news=[])
    if plan:
        signal["target_plan"] = plan
    with patch.object(engine, "now_z", return_value=AT):
        return engine.record_signal(signal, {}, {}, {}, "synthetic-sec-image-test")


def v2_plan():
    import stock_scanner
    zones = [dict(low=low, high=high, touches=1, pivots=[dict(
        price=low, date="2026-09-21", kind="swing_high", confirmed_at="2026-09-23T20:05:00Z")])
        for low, high in ((98, 98.4), (104.65, 105))]
    with patch.object(stock_scanner, "datetime", wraps=datetime) as clock:
        clock.now.return_value = datetime.fromisoformat(AT.replace("Z", "+00:00"))
        plan = stock_scanner._candidate_target_plan(dict(atr=1, price_zones=zones,
            price_as_of="2026-09-25"), "BUY", 100, {"min_risk_reward": 2})
    assert plan["policy_version"] == "single_target_v2"
    return plan


def bridge():
    assert cloud.SCHEMA_VERSION == 6 and cloud.SUPPORTED_SCHEMAS == (6, 7)
    assert cloud.SEC_SCHEMA7_ROLLBACK_CAPABILITY == "sec-schema7-readers-no-producers"
    assert "stock_sec_intelligence" not in cloud.ROLES["scanner"].split(",")
    assert importlib.util.find_spec("sec_intelligence") is None
    cloud.assert_schema()


def sec_digest():
    with database.get_db_connection() as conn:
        rows = {table: [dict(row) for row in conn.execute("SELECT * FROM " + table + " ORDER BY 1")]
                for table in ("si_universe_snapshots", "si_filing_jobs", "si_transactions",
                              "si_company_snapshots", "si_decisions", "si_checkpoints")}
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def synthetic_sec():
    import sec_intelligence as sec
    assert sec.mode() == "off"
    os.environ["SEC_INTELLIGENCE_MODE"] = "paper"
    os.environ["NEWS_SEC_USER_AGENT"] = "Synthetic Operator test@example.com"
    now = datetime.now(timezone.utc)
    universe_id, verified = sec.save_universe({"AAPL": {"company": "Apple Inc.", "indexes": ["sp500"]}},
                                             {"0000320193": ["AAPL"]}, now)
    assert verified == {"AAPL": "0000320193"}
    filing = dict(accessionNumber="0000320193-26-000001", form="4",
                  acceptanceDateTime=sec._z(now - timedelta(minutes=5)), primaryDocument="ownership.xml")
    assert sec._queue_filing(filing, "0000320193", ["AAPL"], universe_id, now, [10])
    assert not sec._queue_filing(filing, "0000320193", ["AAPL"], universe_id, now, [10])
    xml = b"""<ownershipDocument><documentType>4</documentType><periodOfReport>2026-10-08</periodOfReport>
    <issuer><issuerCik>0000320193</issuerCik></issuer><reportingOwner><reportingOwnerId>
    <rptOwnerCik>0000000042</rptOwnerCik></reportingOwnerId></reportingOwner>
    <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common Stock</value></securityTitle>
    <transactionDate><value>2026-10-08</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>10</value></transactionShares>
    <transactionPricePerShare><value>12</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    with patch.object(sec, "fetch", return_value=(xml, {})):
        assert sec.process_jobs(now)["processed"] == 1
        assert sec.process_jobs(now)["processed"] == 0
    at = datetime.now(timezone.utc)
    candidate = dict(ticker="AAPL", company="Apple Inc.", technical_direction="BUY", technical_score=5)
    assert not sec.snapshots_for([candidate], now - timedelta(minutes=5))
    rows = sec.decorate([candidate], at)
    assert rows[0]["sec_coverage"] == "verified" and rows[0]["sec_adjustment"] > 0
    assert len(sec.current_evidence(rows[0], at, 6)) == 1
    sec.persist_decisions("synthetic-image-scan", rows, {"AAPL"}, at, "paper")
    sec.persist_decisions("synthetic-image-scan", rows, {"AAPL"}, at, "paper")
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM si_decisions").fetchone()["n"] == 1
        assert conn.execute("SELECT COUNT(*) n FROM si_transactions").fetchone()["n"] == 1
        assert engine.enqueue_telegram(conn, "synthetic-sec-rollback", "sec_intelligence", "synthetic")
    (ROOT / "sec-digest").write_text(sec_digest())
    os.environ["SEC_INTELLIGENCE_MODE"] = "off"


def backup():
    import recovery_state as recovery
    data = recovery.export_postgres(os.environ["DATABASE_URL"])
    assert data["version"] == data["recovery_format"] == 3
    assert len(data["hold_coverage"]["order_ids"]) == 1
    assert data["hold_coverage"]["entry_reserved_notional"] == state()["reserved"][0]["amount"]
    assert any(order["status"] == "imported" for order in data["tables"]["scanner_orders"])
    assert any(trade["is_shadow"] for trade in data["tables"]["scanner_trades"])
    assert not any(table.startswith("si_") for table in data["tables"])
    key = ROOT / "synthetic-identity"
    if not key.exists():
        subprocess.run(["age-keygen", "-o", str(key)], capture_output=True, check=True)
    recipient = subprocess.check_output(["age-keygen", "-y", str(key)]).decode().strip()
    encrypted, _sizes = recovery.encrypted_bytes(data, recipient)
    (ROOT / "synthetic.age").write_bytes(encrypted)
    assert recovery.decrypt(ROOT / "synthetic.age", key) == data
    import sec_history
    archive = sec_history.export_archive(os.environ['DATABASE_URL'], ROOT / 'sec-archive', recipient)
    if schema() == 7:
        assert archive is not None
        (ROOT / 'sec-manifest').write_text(archive['manifest_path'])
        (ROOT / 'sec-archive-digest').write_text(sec_digest())
    else:
        assert archive is None  # schema 6 is absent coverage, not an empty archive
    return data


def main(phase):
    if phase == "seed":
        sys.argv = ["cloud_runtime.py", "migrate"]
        cloud.main()
        cloud.assert_schema()
        assert schema() == 6
        with database.get_db_connection() as conn:
            conn.execute("INSERT INTO agents(name,token,cash) VALUES('us-stock-scanner','synthetic',100000)")
        engine.initialize_runtime()
        record("V1FIXTURE")
        engine.process_bar("V1FIXTURE", BAR)
        os.environ["STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED"] = "true"
        plan = v2_plan()
        record("AAPL", plan)
        engine.process_bar("AAPL", BAR)
        record("V2HOLD", plan)
        missing_at = datetime(2026, 9, 29, 14, tzinfo=timezone.utc)
        with patch.object(engine, "datetime", wraps=datetime) as clock, patch.object(engine, "_bar_dicts", return_value=[]):
            clock.now.side_effect = lambda tz=None: missing_at.astimezone(tz)
            engine.monitor_prices()
        sys.path.insert(0, "/app/service/server/tests_pg")
        from test_recovery_holds import seed_legacy
        seed_legacy()
        assert len(state()["holds"]) == 1
        assert state()["holds"][0]["valid_until"] < missing_at.isoformat()
        assert any(trade["is_shadow"] for trade in state()["trades"])
        accounting()
        save("portfolio")
    elif phase == "prepare":
        bridge()
        sys.argv = ["cloud_runtime.py", "migrate"]
        cloud.main()
        assert schema() == 6
        engine.initialize_runtime()
        unchanged("portfolio")
        accounting()
        leases()
        backup()
    elif phase == "baseline_return":
        cloud.assert_schema()
        assert schema() == 6
        engine.initialize_runtime()
        unchanged("portfolio")
        accounting()
    elif phase in ("immediate_failure", "rollback", "restart"):
        bridge()
        assert schema() == 7
        engine.initialize_runtime()
        unchanged("portfolio")
        assert record("V2HOLD")["status"] == "DUPLICATE_BLOCKED"
        engine.process_bar("AAPL", BAR)
        engine.process_bar("V1FIXTURE", BAR)
        with patch.object(engine, "_bar_dicts", return_value=[]):
            engine.monitor_prices()
        unchanged("portfolio")
        accounting()
        leases()
        if phase == "rollback":
            assert sec_digest() == (ROOT / "sec-digest").read_text()
            engine.process_telegram_outbox(limit=200)
            with database.get_db_connection() as conn:
                alert = conn.execute("SELECT status,last_error FROM scanner_telegram_outbox WHERE dedupe_key='synthetic-sec-rollback'").fetchone()
            assert alert["status"] == "cancelled" and alert["last_error"] == "sec_bridge_publication_fenced"
            backup()
    elif phase == "activate":
        cloud.assert_schema()
        assert cloud.SCHEMA_VERSION == 7
        engine.initialize_runtime()
        unchanged("portfolio")
        synthetic_sec()
        unchanged("portfolio")
        accounting()
    elif phase == "restore":
        import recovery_state as recovery
        bridge()
        data = recovery.decrypt(ROOT / "synthetic.age", ROOT / "synthetic-identity")
        recovery.restore(data, os.environ["DATABASE_URL"], "synthetic-scanner-token-longer-than-32")
        engine.initialize_runtime()
        unchanged("portfolio")
        # Check restore/restart before explicitly attempting a new admission.
        # record_signal legitimately queues a new (blocked) signal notice;
        # that notice is not an imported or replayed message.
        with database.get_db_connection() as conn:
            assert conn.execute("SELECT COUNT(*) n FROM scanner_telegram_outbox").fetchone()["n"] == 0
            assert conn.execute("SELECT COUNT(*) n FROM si_decisions").fetchone()["n"] == 0
        import sec_history
        sec_history.restore_archive(ROOT / 'sec-archive', (ROOT / 'sec-manifest').read_text(),
            ROOT / 'synthetic-identity', os.environ['DATABASE_URL'], workers_stopped=True)
        assert sec_digest() == (ROOT / 'sec-archive-digest').read_text()
        unchanged('portfolio')
        assert record("V2HOLD")["status"] == "DUPLICATE_BLOCKED"
        with database.get_db_connection() as conn:
            notices = conn.execute("SELECT event_type FROM scanner_telegram_outbox").fetchall()
            assert len(notices) == 1 and notices[0]["event_type"] == "new_signal"
        try:
            recovery.restore(data, os.environ["DATABASE_URL"], "synthetic-scanner-token-longer-than-32")
        except ValueError as exc:
            assert "already_imported" in str(exc)
        else:
            raise AssertionError("repeat_restore_accepted")
        unchanged("portfolio")
        accounting()
    elif phase == "exit":
        cloud.assert_schema()
        before = state()
        for ticker in ("V1FIXTURE", "AAPL", "TEST"):
            bar = dict(at="2026-09-28T13:40:00Z", open=106, high=107, low=105, close=106)
            engine.process_bar(ticker, bar)
            after = state()
            engine.process_bar(ticker, bar)
            assert state() == after
        assert state()["holds"] == before["holds"] and state()["reserved"] == before["reserved"]
        assert len(state()["fills"]) > len(before["fills"])
        assert all(trade["remaining_quantity"] == 0 for trade in state()["trades"] if trade["status"] == "closed")
        accounting()
        save("exited")
    elif phase == "forward":
        import sec_intelligence as sec
        cloud.assert_schema()
        assert sec.mode() == "off"
        engine.initialize_runtime()
        unchanged("exited")
        accounting()
        leases()
    elif phase == 'history_retention':
        import sec_history
        import sec_retention
        sys.path.insert(0, '/app/service/server/tests_pg')
        from test_sec_history_pg import seed, confirmed
        cloud.assert_schema()
        seed(os.environ['DATABASE_URL'])
        before = state()
        recipient = subprocess.check_output(['age-keygen', '-y', str(ROOT / 'synthetic-identity')]).decode().strip()
        repo = ROOT / 'retained-sec-archive'
        archive = sec_history.export_archive(os.environ['DATABASE_URL'], repo, recipient)
        (ROOT / 'retained-sec-manifest').write_text(archive['manifest_path'])
        (ROOT / 'retained-sec-digest').write_text(sec_digest())
        confirmed(repo, archive)  # real Git round-trip to an isolated local bare remote
        result = sec_retention.prune_archived(os.environ['DATABASE_URL'], repo, archive)
        assert all(result['deleted'][table] == 1 for table in sec_history.TABLES if table != 'si_checkpoints')
        assert state() == before
        accounting()
    elif phase == 'history_restore':
        import sec_history
        bridge()
        sec_history.restore_archive(ROOT / 'retained-sec-archive', (ROOT / 'retained-sec-manifest').read_text(),
            ROOT / 'synthetic-identity', os.environ['DATABASE_URL'], workers_stopped=True)
        assert sec_digest() == (ROOT / 'retained-sec-digest').read_text()
        with database.get_db_connection() as conn:
            for table in ('scanner_accounts', 'scanner_orders', 'scanner_trades', 'scanner_fills', 'scanner_telegram_outbox'):
                assert conn.execute('SELECT COUNT(*) n FROM ' + table).fetchone()['n'] == 0
    elif phase in ("baseline_refused", "invalid_schema_refused"):
        try:
            cloud.assert_schema()
        except RuntimeError:
            pass
        else:
            raise AssertionError("incompatible_database_accepted")
    elif phase == "corrupt_schema":
        cloud.assert_schema()
        with database.get_db_connection() as conn:
            conn.execute("DROP INDEX idx_si_jobs_due")
    else:
        raise ValueError(phase)
    report = dict(phase=phase, result="PASS", build_sha=os.environ["BUILD_SHA"], schema=schema())
    with (ROOT / "results.jsonl").open("a") as output:
        output.write(json.dumps(report) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    with patch.object(requests.sessions.Session, "request", side_effect=AssertionError("external HTTP forbidden")), \
         patch("stock_scanner.send_telegram", side_effect=AssertionError("Telegram forbidden")), \
         patch("telegram_status.refresh_telegram_status_cards", return_value={}):
        main(sys.argv[1])
