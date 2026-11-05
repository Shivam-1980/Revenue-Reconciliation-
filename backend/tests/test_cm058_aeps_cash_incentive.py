import sys
from pathlib import Path
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.reconciliation_engine import reconcile_transactions, aggregate_by_transaction_type
from app.services.monthly_expected import calculate_monthly_components


def test_cm058_expected_is_one_rupee_per_eligible_successful_withdrawal_and_visible_in_type_table():
    tx = pd.DataFrame([
        {"csp_id":"1A851111", "transaction_type":"AEPS ONUS WITHDRAWAL", "amount":1000, "transaction_date":"2026-08-01"},
        {"csp_id":"1A851111", "transaction_type":"AEPS ONUS WITHDRAWAL", "amount":2000, "transaction_date":"2026-08-02"},
        {"csp_id":"1A851111", "transaction_type":"AEPS OFFUS WITHDRAWAL", "amount":500, "transaction_date":"2026-08-03"},
        {"csp_id":"1A851111", "transaction_type":"AEPS ONUS DEPOSIT", "amount":300, "transaction_date":"2026-08-03"},
    ])
    cm = pd.DataFrame([
        {"csp_id":"1A851111", "transaction_type":"ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS", "actual_commission":3, "report_base":3}
    ])
    result = reconcile_transactions(tx, cm, rate_rules=None)
    cm058 = result[result.transaction_type.eq("ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS")]
    assert len(cm058) == 1
    row = cm058.iloc[0]
    assert row.expected_commission == 3
    assert row.actual_commission == 3
    assert row.financial_gap == 0
    table = aggregate_by_transaction_type(result)
    row2 = table[table.transaction_type.eq("ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS")].iloc[0]
    assert row2.expected_commission == 3
    assert row2.bc_report_commission_total == 3
    assert row2.successful_transactions == 3


def test_cm058_expected_not_derived_from_bank_base_when_source_absent():
    cm = pd.DataFrame([{"csp_id":"1A851111", "transaction_type":"ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS", "actual_commission":999, "report_base":999}])
    out = calculate_monthly_components(cm, reconciled_rows=pd.DataFrame())
    row = next(x for x in out["components"] if x["component"] == "Additional incentive on AEPS cash transactions")
    assert row["amount"] is None
    assert row["status"] == "EVIDENCE REQUIRED"
