import sys
from pathlib import Path
import pandas as pd
BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from app.services.women_csp_incentive import reconcile_women_csp_incentive


def test_rule24_uses_core_transaction_commission_and_excludes_separate_incentives():
    roster = pd.DataFrame([
        {"csp_id":"1A850001", "csp_name":"Paid", "transaction_count":100},
        {"csp_id":"1A850002", "csp_name":"Unpaid", "transaction_count":20},
        {"csp_id":"1A850003", "csp_name":"Inactive", "transaction_count":0},
    ])
    bc = pd.DataFrame([
        {"csp_id":"1A850001", "csp_name":"Paid", "transaction_type":"MONEY TRANSFER", "actual_commission":1500.0},
        {"csp_id":"1A850001", "csp_name":"Paid", "transaction_type":"WOMEN CSP INCENTIVE", "actual_commission":150.0},
        {"csp_id":"1A850002", "csp_name":"Unpaid", "transaction_type":"MONEY TRANSFER", "actual_commission":500.0},
        {"csp_id":"1A850003", "csp_name":"Inactive", "transaction_type":"WOMEN CSP INCENTIVE", "actual_commission":0.0},
        {"csp_id":"1A850004", "csp_name":"Extra", "transaction_type":"MONEY TRANSFER", "actual_commission":800.0},
        {"csp_id":"1A850004", "csp_name":"Extra", "transaction_type":"WOMEN CSP INCENTIVE", "actual_commission":80.0},
    ])
    out = reconcile_women_csp_incentive(roster, bc, "2026-08")
    assert out["available"]
    s = out["summary"]
    assert s["matched_in_master_csp_count"] == 1
    assert s["matched_in_master_actual"] == 150.0
    assert s["unpaid_shortfall_csp_count"] == 1
    assert s["unpaid_shortfall_expected"] == 50.0
    assert s["bank_paid_extra_csp_count"] == 1
    assert s["bank_paid_extra_actual"] == 80.0
    assert s["inactive_zero_transaction_csp_count"] == 1
    assert out["rows"][0]["base_transaction_commission"] == 1500.0


def test_rule24_does_not_require_success_reconciliation_output_if_bc_core_base_exists():
    roster = pd.DataFrame([{"csp_id":"1A850001", "transaction_count":10}])
    bc = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"MONEY TRANSFER", "actual_commission":1000.0},
        {"csp_id":"1A850001", "transaction_type":"WOMEN CSP INCENTIVE", "actual_commission":100.0},
    ])
    out = reconcile_women_csp_incentive(roster, bc, "2026-08")
    assert out["available"]
    assert out["rows"][0]["base_transaction_commission"] == 1000.0
    assert out["rows"][0]["expected_incentive"] == 100.0
    assert out["summary"]["matched_in_master_csp_count"] == 1


def test_unknown_commission_type_is_not_added_to_rule24_base():
    roster = pd.DataFrame([{"csp_id":"1A850001", "transaction_count":10}])
    bc = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"MONEY TRANSFER", "actual_commission":100.0},
        {"csp_id":"1A850001", "transaction_type":"NEW UNREVIEWED INCENTIVE", "actual_commission":900.0},
        {"csp_id":"1A850001", "transaction_type":"WOMEN CSP INCENTIVE", "actual_commission":10.0},
    ])
    out = reconcile_women_csp_incentive(roster, bc, "2026-08")
    assert out["rows"][0]["base_transaction_commission"] == 100.0
    assert out["rows"][0]["expected_incentive"] == 10.0
