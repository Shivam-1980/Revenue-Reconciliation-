import csv
import pandas as pd
from app.services.women_csp_incentive import reconcile_women_csp_incentive
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_sbi_rule24_is_permanent_and_evidence_gated():
    with (ROOT / 'docs' / 'SBI_RULE_CATALOG.csv').open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    row = next(r for r in rows if r.get('rule_id') == 'SBI-24')
    assert row['transaction_type'] == 'WOMEN CSP INCENTIVE'
    assert float(row['rate']) == 10.0
    assert float(row['cap']) == 1000.0
    assert row['rule_status'] == 'EVIDENCE_REQUIRED'
    assert 'approved Women CSP' in row['remarks']



def test_rule24_is_included_only_in_extended_management_kpi_scope():
    from app.services.control_kpi import controlled_reconciliation_kpi

    # The primary transaction-only KPI remains independent from monthly incentives.
    primary = controlled_reconciliation_kpi(transaction_matched=50, transaction_groups=100)
    assert primary == (50, 100, 50.0)

    # Extended management KPI includes a separate Women CSP control population.
    extended = controlled_reconciliation_kpi(
        transaction_matched=50, transaction_groups=100,
        rural_matched=8, rural_groups=10,
        dfs_matched=4, dfs_groups=5,
        women_csp_matched=7, women_csp_groups=10,
    )
    assert extended == (69, 125, 55.2)


def test_rule24_exception_rows_remain_in_denominator_not_as_matches():
    from app.services.control_kpi import controlled_reconciliation_kpi

    # 7 matched of 10 Women CSP controls: 3 unpaid/extra/variance rows are exceptions.
    result = controlled_reconciliation_kpi(
        transaction_matched=0, transaction_groups=0,
        women_csp_matched=7, women_csp_groups=10,
    )
    assert result == (7, 10, 70.0)


def test_rule24_falls_back_to_approved_expected_amount_when_verified_field_is_null():
    roster = pd.DataFrame([{"csp_id": "1A850001", "csp_name": "CSP A", "transaction_count": 10}])
    bc = pd.DataFrame([
        {"csp_id": "1A850001", "csp_name": "CSP A", "transaction_type": "MONEY TRANSFER", "actual_commission": 1000.0},
        {"csp_id": "1A850001", "csp_name": "CSP A", "transaction_type": "WOMEN CSP INCENTIVE", "actual_commission": 100.0},
    ])
    expected = pd.DataFrame([{
        "csp_id": "1A850001", "transaction_type": "MONEY TRANSFER",
        "expected_commission": 1000.0, "verified_expected_commission": None,
        "settlement_rule_approved": True,
    }])
    out = reconcile_women_csp_incentive(roster, bc, "2026-08", expected_transactions=expected)
    assert out["available"]
    assert out["rows"][0]["base_transaction_commission"] == 1000.0
    assert out["rows"][0]["expected_incentive"] == 100.0
    assert out["summary"]["matched_in_master_csp_count"] == 1


def test_rule24_base_uses_applied_rate_even_when_settlement_comparison_is_not_approved():
    roster = pd.DataFrame([{"csp_id": "1A850001", "csp_name": "CSP A", "transaction_count": 20}])
    bc = pd.DataFrame([
        {"csp_id": "1A850001", "csp_name": "CSP A", "transaction_type": "MONEY TRANSFER", "actual_commission": 1000.0},
        {"csp_id": "1A850001", "csp_name": "CSP A", "transaction_type": "WOMEN CSP INCENTIVE", "actual_commission": 100.0},
    ])
    expected = pd.DataFrame([{
        "csp_id": "1A850001", "transaction_type": "MONEY TRANSFER",
        "expected_commission": 1000.0, "verified_expected_commission": 1000.0,
        "rate_status": "Applied", "settlement_rule_approved": False,
    }])
    out = reconcile_women_csp_incentive(roster, bc, "2026-08", expected_transactions=expected)
    assert out["available"]
    assert out["rows"][0]["base_transaction_commission"] == 1000.0
    assert out["rows"][0]["expected_incentive"] == 100.0


def test_rule24_includes_explicit_imps_fund_transfer_variants_but_not_ambiguous_money_transfer():
    import pandas as pd
    from app.services.women_csp_incentive import reconcile_women_csp_incentive
    roster = pd.DataFrame([{'csp_id': '1A850001', 'csp_name': 'A', 'transaction_count': 1}])
    bc = pd.DataFrame([
        {'csp_id': '1A850001', 'csp_name': 'A', 'transaction_type': 'IMPS FUND TRANSFER', 'actual_commission': 100.00},
        {'csp_id': '1A850001', 'csp_name': 'A', 'transaction_type': 'IMPS FUNDTRANFER', 'actual_commission': 50.00},
        {'csp_id': '1A850001', 'csp_name': 'A', 'transaction_type': 'IMPS MONEY TRANSFER', 'actual_commission': 25.00},
    ])
    result = reconcile_women_csp_incentive(roster, bc, period='2026-09')
    row = next(r for r in result['rows'] if r['csp_id'] == '1A850001')
    assert row['base_transaction_commission'] == 150.00
    assert row['expected_incentive'] == 15.00
