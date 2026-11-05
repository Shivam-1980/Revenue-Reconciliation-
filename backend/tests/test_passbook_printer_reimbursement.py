import sys
from pathlib import Path
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.monthly_expected import calculate_monthly_components

def _row(result):
    return next(c for c in result["components"] if c["component"] == "Passbook printer cost reimbursement")

def test_printer_reimbursement_uses_bc_report_quantity_times_monthly_rate():
    commission = pd.DataFrame({
        "transaction_type": ["PASSBOOK PRINTER COST REIMBURSEMENT"] * 50,
        "csp_id": [f"1A85{i:04d}" for i in range(50)],
        "report_base": [1] * 50,
        "commission": [610] * 50,
    })
    result = calculate_monthly_components(commission)
    row = _row(result)
    assert row["status"] == "VERIFIED"
    assert row["amount"] == 30500.0
    assert row["actual_amount"] == 30500.0
    assert row["actual_paid_printer_months"] == 50
    assert row["variance"] == 0.0
    assert result["verified_earnings"] == 30500.0

def test_printer_reimbursement_not_present_when_no_bank_rows():
    result = calculate_monthly_components(pd.DataFrame(columns=["transaction_type", "csp_id", "report_base", "commission"]))
    assert not any(c["component"] == "Passbook printer cost reimbursement" for c in result["components"])

def test_printer_reimbursement_reads_normalized_actual_commission_column():
    commission = pd.DataFrame({
        "transaction_type": ["PASSBOOK PRINTER COST REIMBURSEMENT"] * 50,
        "csp_id": [f"1A85{i:04d}" for i in range(50)],
        "report_base": [1] * 50,
        "actual_commission": [610] * 50,
    })
    row = _row(calculate_monthly_components(commission))
    assert row["actual_amount"] == 30500.0
    assert row["amount"] == 30500.0

def test_printer_reimbursement_count_mismatch_is_conditional():
    commission = pd.DataFrame({
        "transaction_type": ["PASSBOOK PRINTER COST REIMBURSEMENT"] * 50,
        "csp_id": [f"1A85{i:04d}" for i in range(50)],
        "report_base": [1] * 50,
        "actual_commission": [610] * 49 + [500],
    })
    row = _row(calculate_monthly_components(commission))
    assert row["amount"] == 30500.0
    assert row["actual_amount"] == 30390.0
    assert row["variance"] == -110.0
    assert row["status"] == "CONDITIONAL"
