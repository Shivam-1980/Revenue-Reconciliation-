"""Regression tests for the user-supplied SBI Rural CSP Incentive rule (Rule 9)."""
import sys
from pathlib import Path
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.rural_commission import reconcile_rural_commission


def _mapping():
    return pd.DataFrame([
        {"transaction_type": "ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE", "count_as_txn": "Y", "reason": "PMJDY account opening"},
        {"transaction_type": "APPROVED FINANCIAL TXN", "count_as_txn": "Y", "reason": "Approved txn"},
    ])


def _commission(rows):
    return pd.DataFrame(rows, columns=["csp_id", "transaction_type", "report_base", "actual_commission", "channel"])


def test_rule9_uses_twenty_login_days_and_pmjdy_or_txn_threshold():
    master = pd.DataFrame([
        {"csp_id": "1A850001", "csp_name": "PMJDY threshold", "csp_category": "Gold CSP", "relationship_manager": "RM", "login_days": 20, "period": "2026-08"},
        {"csp_id": "1A850002", "csp_name": "Txn threshold", "csp_category": "Silver CSP", "relationship_manager": "RM", "login_days": 21, "period": "2026-08"},
        {"csp_id": "1A850003", "csp_name": "Both below threshold", "csp_category": "Silver CSP", "relationship_manager": "RM", "login_days": 25, "period": "2026-08"},
        {"csp_id": "1A850004", "csp_name": "Login below threshold", "csp_category": "Gold CSP", "relationship_manager": "RM", "login_days": 19, "period": "2026-08"},
    ])
    cm = _commission([
        ("1A850001", "ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE", 50, 0, "RURAL"),
        ("1A850002", "APPROVED FINANCIAL TXN", 100, 0, "SEMI URBAN"),
        ("1A850003", "APPROVED FINANCIAL TXN", 99, 0, "RURAL"),
        ("1A850004", "ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE", 50, 0, "RURAL"),
    ])
    result = reconcile_rural_commission(cm, transaction_month="2026-08", rural_master=master, txn_mapping=_mapping())
    assert result["available"] is True
    rows = {r["csp_id"]: r for r in result["rows"]}
    assert rows["1A850001"]["eligible"] is True  # PMJDY threshold alone is enough
    assert rows["1A850001"]["expected_commission"] == 2000
    assert rows["1A850002"]["eligible"] is True  # transaction threshold alone is enough
    assert rows["1A850002"]["expected_commission"] == 2000
    assert rows["1A850003"]["eligible"] is False
    assert rows["1A850003"]["expected_commission"] == 0
    assert rows["1A850004"]["eligible"] is False  # login condition is mandatory
    assert result["summary"]["eligible_csp_count"] == 2
    assert result["summary"]["expected_commission"] == 4000


def test_rule9_urban_metro_is_not_applicable_even_when_thresholds_pass():
    master = pd.DataFrame([
        {"csp_id": "1A850010", "csp_name": "Urban CSP", "csp_category": "Gold CSP", "relationship_manager": "RM", "login_days": 25, "period": "2026-09"},
    ])
    cm = _commission([
        ("1A850010", "ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE", 50, 0, "URBAN"),
    ])
    result = reconcile_rural_commission(cm, transaction_month="2026-09", rural_master=master, txn_mapping=_mapping())
    row = result["rows"][0]
    assert row["urban_metro_not_applicable"] is True
    assert row["eligible"] is False
    assert row["expected_commission"] == 0
    assert row["status"] == "Not applicable - Urban/Metro"
    assert result["summary"]["urban_metro_not_applicable_count"] == 1


def test_rule9_period_must_match_uploaded_month():
    master = pd.DataFrame([
        {"csp_id": "1A850020", "csp_name": "CSP", "csp_category": "Gold CSP", "relationship_manager": "RM", "login_days": 25, "period": "2026-08"},
    ])
    result = reconcile_rural_commission(_commission([]), transaction_month="2026-09", rural_master=master, txn_mapping=_mapping())
    assert result["available"] is False
    assert result["status"] == "PERIOD_MISMATCH"


def test_rule9_missing_login_evidence_does_not_guess_expected_commission():
    master = pd.DataFrame([
        {"csp_id": "1A850030", "csp_name": "Missing login", "csp_category": "Gold CSP", "relationship_manager": "RM", "login_days": float("nan"), "period": "2026-08"},
    ])
    cm = _commission([
        ("1A850030", "ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE", 50, 0, "RURAL"),
    ])
    result = reconcile_rural_commission(cm, transaction_month="2026-08", rural_master=master, txn_mapping=_mapping())
    row = result["rows"][0]
    assert row["status"] == "Login days missing - verify"
    assert row["eligibility_assessed"] is False
    assert pd.isna(row["expected_commission"])
    assert result["summary"]["eligibility_unresolved_count"] == 1
