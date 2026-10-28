"""Public SEC copy/selection only, synthetic facts and no provider/model calls."""
import copy
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sec_intelligence as si
import database

JOB = {"accession": "0000000001-26-000001", "accepted_at": "2026-10-20T12:00:00Z"}
TAGS = {"revenue": "Revenues", "operating_income": "OperatingIncomeLoss",
        "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
        "cash": "CashAndCashEquivalentsAtCarryingValue", "current_debt": "LongTermDebtCurrent",
        "long_term_debt": "LongTermDebtNoncurrent", "operating_margin": "operating_income/revenue"}


def comparison(metric="revenue", *, year=2026, value=120, previous=100,
               start_month="07-01", end_month="09-30"):
    instant = metric in {"cash", "current_debt", "long_term_debt"}
    margin = metric == "operating_margin"
    return {"metric": metric, "namespace": "derived" if margin else "us-gaap", "tag": TAGS[metric],
            "unit": "percent" if margin else "USD", "accession": JOB["accession"],
            "start": None if instant else f"{year}-{start_month}", "end": f"{year}-{end_month}",
            "value": value, "previous": {"value": previous, "accession": "synthetic-prior",
                "start": None if instant else f"{year-1}-{start_month}", "end": f"{year-1}-{end_month}",
                "filed": f"{year-1}-10-20"},
            "change_pct": None if margin or previous == 0 else round((value / previous - 1) * 100, 3),
            "reason": "zero_denominator" if previous == 0 else "comparable_prior",
            **({"change_pp": value-previous} if margin else {})}


def render(*facts):
    return si._material_public_fact(JOB, {"kind": "financial", "comparisons": list(facts)}, None)


@pytest.fixture(autouse=True)
def isolated_controls(monkeypatch):
    monkeypatch.setenv("SEC_INTELLIGENCE_MATERIAL_CHANGE_PCT", "10")
    monkeypatch.setenv("SEC_INTELLIGENCE_MATERIAL_MARGIN_PP", "2")
    monkeypatch.setattr(si, "fetch", lambda *_a, **_k: pytest.fail("No source fetch in editorial tests"))
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *_a, **_k: pytest.fail("No HTTP in editorial tests"))


@pytest.mark.parametrize("reverse", [False, True])
def test_latest_period_selected_before_largest_historical_percentage(reverse):
    facts = [comparison(value=120), comparison(year=2025, value=100, previous=25)]
    if reverse:
        facts.reverse()
    text = render(*facts)
    assert "20.0%" in text and "300.0%" not in text
    assert "2026-07-01" in text and "2026-09-30" in text and "2025-07-01" in text


def test_nonmaterial_latest_period_does_not_revive_material_comparative_period():
    assert render(comparison(value=105), comparison(year=2025, value=100, previous=25)) is None


def test_operating_results_not_displaced_by_tiny_base_cash_or_debt():
    text = render(comparison(value=1_200_000_000, previous=1_000_000_000),
                  comparison("cash", value=2000, previous=1000),
                  comparison("current_debt", value=3000, previous=1000))
    assert "הכנסות" in text and "20.0%" in text
    assert "1,200,000,000" in text and "1,000,000,000" in text and "USD" in text
    assert "מזומן" not in text and "חוב" not in text


def test_cash_or_debt_without_contemporaneous_operating_context_is_not_a_notice():
    assert render(comparison("cash", value=200, previous=100),
                  comparison("current_debt", value=300, previous=100)) is None


def test_selected_fact_displays_exact_period_values_unit_and_no_causal_claim():
    text = render(comparison(value=1200, previous=1000))
    assert all(value in text for value in ("2026-07-01", "2026-09-30", "2025-07-01", "2025-09-30", "1,200", "1,000", "USD", "20.0%"))
    assert "בגלל" not in text and "תחזית לתשואה" not in text


def test_material_cash_balance_can_accompany_matching_operating_cash_flow():
    text = render(comparison("operating_cash_flow", value=200, previous=100),
                  comparison("cash", value=400, previous=200))
    assert "תזרים מפעילות שוטפת" in text and "מזומן" in text
    assert "ליום 2026-09-30" in text and "2025-09-30" in text
    assert "מצוקה" not in text and "נזילות השתפרה" not in text


def test_balance_context_must_match_both_period_ends():
    text = render(comparison("operating_cash_flow", value=200),
                  comparison("cash", year=2025, value=400, previous=200))
    assert "תזרים מפעילות שוטפת" in text and "• מזומן" not in text


def test_margin_uses_percentage_points_and_signed_reported_values():
    text = render(comparison("operating_margin", value=5, previous=-2))
    assert "מרווח תפעולי" in text and "נקודות אחוז" in text
    assert "5" in text and "-2" in text and "7.0" in text
    assert "USD" not in text


def test_positive_base_to_loss_is_not_hidden_by_sign_and_no_zero_division():
    text = render(comparison("operating_income", value=-50, previous=100))
    assert "-50" in text and "100" in text and "150.0%" in text
    assert render(comparison("operating_income", value=10, previous=0)) is None
    assert render(comparison("operating_income", value=10, previous=-5)) is None


@pytest.mark.parametrize("change", [
    lambda f: f.update(unit="EUR"),
    lambda f: f["previous"].pop("end"),
    lambda f: f["previous"].update(start="2025-01-01"),
    lambda f: f.update(value=float("nan")),
    lambda f: f.update(value=True),
    lambda f: f.update(namespace="unsupported"),
    lambda f: f.update(tag="CashAndCashEquivalentsAtCarryingValue"),
])
def test_missing_incompatible_or_nonfinite_context_is_never_guessed(change):
    fact = comparison()
    change(fact)
    assert render(fact) is None


def test_formatter_does_not_mutate_evidence_or_research_controls():
    facts = [comparison(), comparison("operating_income", value=150)]
    frozen, controls = copy.deepcopy(facts), si.research_controls()
    assert render(*facts)
    assert facts == frozen and si.research_controls() == controls


def test_conflicting_latest_alias_is_not_hidden_by_its_unknown_comparator():
    good, unknown = comparison(), comparison(value=250)
    unknown.update(tag="RevenueFromContractWithCustomerExcludingAssessedTax",
                   previous=None, reason="no_comparable_prior", change_pct=None)
    assert render(good, unknown) is None


def test_nonfinite_latest_alias_cannot_authorize_other_alias_comparison():
    good, unknown = comparison(), comparison()
    unknown.update(value=float("nan"), previous=None, reason="no_comparable_prior", change_pct=None)
    assert render(good, unknown) is None


def test_quarter_ytd_and_annual_are_not_merged_or_used_to_guess_periods():
    quarter = comparison(value=120)
    ytd = comparison(value=500, start_month="01-01")
    annual = comparison(year=2025, value=100, previous=50, start_month="01-01", end_month="12-31")
    assert render(quarter, ytd) == render(quarter)
    # Latest retained quarter beats older annual for the same metric, but
    # report both exact periods when an annual is the only usable duration.
    assert "20.0%" in render(quarter, annual)
    assert "2025-12-31" in render(annual) and "2024-12-31" in render(annual)


def test_maximum_three_operating_facts_without_percentage_magnitude_ranking():
    facts = [comparison(), comparison("operating_income", value=150),
             comparison("operating_cash_flow", value=200),
             comparison("operating_margin", value=15, previous=10),
             comparison("cash", value=1000), comparison("current_debt", value=10_000)]
    text = render(*reversed(facts))
    blocks = [block for block in text.split("\n\n") if block.startswith("• ")]
    assert len(blocks) == 3 and all("USD" in block for block in blocks)
    assert "הכנסות" in blocks[0] and "רווח תפעולי" in blocks[1] and "תזרים מפעילות שוטפת" in blocks[2]
    assert "• מזומן" not in text and "• חוב" not in text
    assert len(text) < 2000 and "https://" not in text


@pytest.mark.parametrize("metric,meaning", [
    ("revenue", "היקף ההכנסות"), ("operating_income", "תוצאת הפעילות התפעולית"),
    ("operating_margin", "הרווח התפעולי ביחס להכנסות"),
    ("operating_cash_flow", "כסף שנוצר או שימש בפעילות")])
def test_significance_defines_the_measured_metric_without_invented_impact(metric, meaning):
    fact = comparison(metric, value=15, previous=10) if metric == "operating_margin" else comparison(metric)
    text = render(fact)
    assert meaning in text and "הגורם לשינוי" in text
    assert not any(claim in text for claim in ("המניה תעלה", "מחיר יעד", "מצוקה", "בגלל"))


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_TRADER_CLOUD", "false")
    monkeypatch.setattr(database, "DATABASE_URL", "")
    monkeypatch.setattr(database, "_SQLITE_DB_PATH", str(tmp_path / "sec-public-only.db"))
    database.init_database()
    return database.get_db_connection


def seeded_public_process(monkeypatch, *, period_conflict=False, stale=False):
    """Actual process_jobs/outbox on the caller's disposable SQLite/PG schema."""
    now = datetime.now(timezone.utc)
    monkeypatch.setenv("SEC_INTELLIGENCE_MODE", "paper")
    monkeypatch.setenv("SEC_INTELLIGENCE_KILL_SWITCH", "false")
    monkeypatch.setenv("STOCK_SCANNER_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_SEC_INTELLIGENCE_THREAD_ID", "345")
    monkeypatch.setenv("TELEGRAM_COMPANY_REPORTS_THREAD_ID", "346")
    monkeypatch.setenv("SEC_INTELLIGENCE_PUBLIC_NOT_BEFORE", si._z(now-timedelta(days=1)))
    monkeypatch.setenv("NEWS_SEC_USER_AGENT", "Isolated Operator fixture@example.invalid")
    uid, _ = si.save_universe({"TEST": {"company": "Synthetic Issuer", "indexes": ["sp500"]}},
                              {"0000000001": ["TEST"]}, now)
    accepted = now-timedelta(hours=8 if stale else 0, minutes=5)
    si._queue_filing({"accessionNumber": JOB["accession"], "form": "10-Q/A",
                      "acceptanceDateTime": si._z(accepted), "primaryDocument": "report.htm"},
                     "0000000001", ["TEST"], uid, now, [10])
    facts = [comparison(), comparison(year=2025, value=100, previous=25),
             comparison("cash", value=3000, previous=1000)]
    if period_conflict:
        facts[0].update(previous=None, reason="no_comparable_prior", change_pct=None)
    evidence = {"kind": "financial", "document_sha256": hashlib.sha256(b"synthetic").hexdigest(),
                "comparisons": facts}
    original = copy.deepcopy(evidence)
    monkeypatch.setattr(si, "fetch", lambda *_a, **_k: (b"synthetic", {}))
    monkeypatch.setattr(si, "_filing_evidence", lambda *_a, **_k: (evidence, []))
    assert si.process_jobs(now)["processed"] == 1
    assert si.process_jobs(now)["processed"] == 0
    assert evidence == original
    with database.get_db_connection() as conn:
        job = conn.execute("SELECT status,evidence_json FROM si_filing_jobs WHERE accession=?", (JOB["accession"],)).fetchone()
        assert job["status"] == "processed" and json.loads(job["evidence_json"]) == original
        rows = [dict(row) for row in conn.execute("SELECT message,dedupe_key,status,event_type FROM scanner_telegram_outbox")]
        for table in ("scanner_signals", "scanner_orders", "scanner_trades", "scanner_fills", "scanner_final_ai_telemetry"):
            assert conn.execute("SELECT count(*) n FROM " + table).fetchone()["n"] == 0
    return rows


def test_public_process_preserves_evidence_correction_and_once_per_accession(isolated, monkeypatch):
    rows = seeded_public_process(monkeypatch)
    assert len(rows) == 1
    row = rows[0]
    assert row["dedupe_key"] == "sec-intelligence:" + JOB["accession"]
    assert row["status"] == "pending" and row["event_type"] == "sec_intelligence"
    assert "תיקון לדיווח קודם" in row["message"]
    assert "20.0%" in row["message"] and "300.0%" not in row["message"]
    assert "2026-07-01" in row["message"] and "2025-07-01" in row["message"]
    assert "• מזומן" not in row["message"] and "https://" not in row["message"]


@pytest.mark.parametrize("kind", ["uncomparable_latest", "stale_filing"])
def test_public_silence_does_not_discard_or_retry_processed_evidence(isolated, monkeypatch, kind):
    assert seeded_public_process(monkeypatch, period_conflict=kind == "uncomparable_latest",
                                 stale=kind == "stale_filing") == []


def test_8k_scope_remains_unchanged():
    assert si._material_public_fact(JOB, {"kind": "current_report", "specific_guidance_updates": ["synthetic"]}, None) is None
