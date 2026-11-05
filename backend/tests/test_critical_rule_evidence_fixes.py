from pathlib import Path
import pandas as pd
from app.services.rate_master import build_rate_master_from_workbook, calculate_expected

RULE_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "expected_commission_rule" / "latest.xlsx"


def _rules():
    rules, meta = build_rate_master_from_workbook(RULE_PATH.read_bytes(), RULE_PATH.name)
    assert meta["valid"]
    return rules


def test_green_pin_false_first_time_flag_does_not_pay_first_time_commission():
    tx = pd.DataFrame([{
        "transaction_id": "gp-repeat", "csp_id": "C1",
        "rule_type": "GREEN PIN GENERATION", "amount": 0,
        "transaction_date": "2026-08-12", "first_time": "No"
    }])
    out, _ = calculate_expected(tx, _rules())
    assert float(out.iloc[0]["expected_commission"]) == 0.0
    assert out.iloc[0]["rate_status"] == "Condition Not Met"
    assert bool(out.iloc[0]["condition_failure"])


def test_green_pin_blank_first_time_flag_is_evidence_required_not_paid():
    tx = pd.DataFrame([{
        "transaction_id": "gp-unknown", "csp_id": "C1",
        "rule_type": "GREEN PIN GENERATION", "amount": 0,
        "transaction_date": "2026-08-12", "first_time": ""
    }])
    out, _ = calculate_expected(tx, _rules())
    assert pd.isna(out.iloc[0]["expected_commission"])
    assert out.iloc[0]["rate_status"] == "Evidence Required"
    assert bool(out.iloc[0]["required_evidence_missing"])


def test_imps_overlapping_products_are_not_silently_calculated():
    tx = pd.DataFrame([{
        "transaction_id": "imps-overlap", "csp_id": "C1",
        "rule_type": "IMPS MONEY TRANSFER", "amount": 3000,
        "transaction_date": "2026-08-12"
    }])
    out, _ = calculate_expected(tx, _rules())
    assert pd.isna(out.iloc[0]["expected_commission"])
    assert out.iloc[0]["rate_status"] == "Ambiguous Product Variant"
    assert bool(out.iloc[0]["required_evidence_missing"])
    assert "IMPS Cash vs IMPS Transfer" in out.iloc[0]["condition_fail_reason"]


def test_commission_period_must_cover_full_transaction_period():
    from app.api.reconciliation import _period_coverage_problem
    assert _period_coverage_problem("2026-08-01", "2026-08-31", "2026-08-01", "2026-08-31") is None
    msg = _period_coverage_problem("2026-08-01", "2026-08-31", "2026-08-15", "2026-08-31")
    assert msg and "not fully covered" in msg


def test_non_overlapping_periods_are_rejected():
    from app.api.reconciliation import _period_coverage_problem
    msg = _period_coverage_problem("2026-08-01", "2026-08-31", "2026-09-01", "2026-09-30")
    assert msg and "does not overlap" in msg


def test_uploaded_rule_master_separates_imps_product_schedules():
    rules, meta = _rules(), None
    from app.services.rate_master import build_rate_master_from_workbook
    source = Path(__file__).resolve().parents[1] / "app" / "data" / "expected_commission_rule" / "latest.xlsx"
    _, meta = build_rate_master_from_workbook(source.read_bytes(), source.name)
    assert meta.get("overlapping_slab_pairs", 0) == 0
    assert set(rules.loc[rules['rule_id'].isin(['RM-EC-27','RM-EC-28']), 'transaction_type']) == {'IMPS CASH', 'IMPS TRANSFER'}


def test_imps_cash_and_transfer_have_distinct_sbi_calculations():
    rules = _rules()
    tx = pd.DataFrame([
        {"transaction_id": "cash-2000", "csp_id": "C1", "rule_type": "IMPS CASH", "amount": 2000, "transaction_date": "2026-08-12"},
        {"transaction_id": "transfer-2000", "csp_id": "C1", "rule_type": "IMPS TRANSFER", "amount": 2000, "transaction_date": "2026-08-12"},
        {"transaction_id": "cash-5000", "csp_id": "C1", "rule_type": "IMPS CASH", "amount": 5000, "transaction_date": "2026-08-12"},
        {"transaction_id": "transfer-30000", "csp_id": "C1", "rule_type": "IMPS TRANSFER", "amount": 30000, "transaction_date": "2026-08-12"},
    ])
    out, _ = calculate_expected(tx, rules)
    assert out["expected_commission"].tolist() == [11.2, 7.0, 28.0, 50.0]
    assert out["rate_status"].tolist() == ["Applied"] * 4


def test_generic_imps_money_transfer_stays_unresolved():
    tx = pd.DataFrame([{
        "transaction_id": "generic-imps", "csp_id": "C1",
        "rule_type": "IMPS MONEY TRANSFER", "amount": 3000,
        "transaction_date": "2026-08-12"
    }])
    out, _ = calculate_expected(tx, _rules())
    assert pd.isna(out.iloc[0]["expected_commission"])
    assert out.iloc[0]["rate_status"] == "Ambiguous Product Variant"
    assert bool(out.iloc[0]["required_evidence_missing"])


def test_imps_source_labels_resolve_to_distinct_product_types():
    from app.services.reconciliation_engine import resolve_transaction_type
    assert resolve_transaction_type("IMPS - Cash") == "IMPS CASH"
    assert resolve_transaction_type("IMPS - Transfer") == "IMPS TRANSFER"
    assert resolve_transaction_type("IMPS CASH") == "IMPS CASH"
    assert resolve_transaction_type("IMPS TRANSFER") == "IMPS TRANSFER"
