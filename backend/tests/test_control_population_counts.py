import pandas as pd
from app.services.control_population import summarize_control_population, transaction_population_mask

def test_incentive_control_base_does_not_inflate_transaction_population():
    rows = pd.DataFrame([
        {"transaction_type":"AEPS ONUS WITHDRAWAL", "successful_transactions":10, "is_supplemental":False},
        {"transaction_type":"UNMAPPED SOURCE TYPE", "successful_transactions":2, "is_supplemental":pd.NA},
        {"transaction_type":"ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS", "successful_transactions":100, "is_supplemental":True},
        {"transaction_type":"PMJJBY", "successful_transactions":5, "is_supplemental":True},
        {"transaction_type":"PASSBOOK PRINTING", "successful_transactions":8, "is_supplemental":True},
    ])
    result = summarize_control_population(rows)
    assert result["reconciliation_population_transactions"] == 25
    assert result["supplemental_scheme_transactions"] == 5
    assert result["social_security_supplemental_transactions"] == 5
    assert result["passbook_printing_supplemental_transactions"] == 8
    assert result["aeps_cash_incentive_control_transactions"] == 100
    mask = transaction_population_mask(rows)
    assert int(rows.loc[mask, "successful_transactions"].sum()) == 25

def test_empty_population_has_zero_counts():
    result = summarize_control_population(pd.DataFrame())
    assert result["reconciliation_population_transactions"] == 0
    assert result["supplemental_scheme_transactions"] == 0


def test_zero_activity_csp_months_do_not_dilute_incentive_kpi():
    from app.services.control_kpi import active_csp_month_control_groups
    # One source-active control, one bank-only payout, and two roster-only
    # CSPs with no activity/payment. Only the first two count.
    expected = [300, 0, 0, 0]
    actual = [300, 0, 610, 0]
    assert active_csp_month_control_groups(expected, actual) == 2
