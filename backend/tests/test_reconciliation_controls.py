"""Synthetic regression tests for clean-upload releases (no bundled August data)."""
import sys
from pathlib import Path
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.reconciliation_engine import (
    _single_calendar_month_from_transactions, _transaction_months_from_transactions,
    _period_month, _supplement_periods_match, social_security_supplement_active,
    passbook_supplement_active, _pmjjby_rate_for_period,
)


def tx(dates):
    return pd.DataFrame({"transaction_date": pd.to_datetime(dates)})


def supplement(types, periods):
    return pd.DataFrame({"transaction_type": types, "period": periods, "csp_code": [f"C{i}" for i in range(len(types))], "count": [1] * len(types)})


def test_single_month_august_detected():
    assert _single_calendar_month_from_transactions(tx(["2026-08-01", "2026-08-31"])) == "2026-08"

def test_single_month_september_detected():
    assert _single_calendar_month_from_transactions(tx(["2026-09-01", "2026-09-30"])) == "2026-09"

def test_multi_month_file_not_misclassified_as_single_month():
    assert _single_calendar_month_from_transactions(tx(["2026-08-31", "2026-09-01"])) is None

def test_months_sorted_and_unique():
    assert _transaction_months_from_transactions(tx(["2026-09-01", "2026-08-31", "2026-09-02"])) == ["2026-08", "2026-09"]

def test_period_iso_normalizes():
    assert _period_month("2026-08") == "2026-08"

def test_period_month_name_normalizes():
    assert _period_month("AUGUST 2026") == "2026-08"

def test_period_abbreviated_name_normalizes():
    assert _period_month("Sep-2026") == "2026-09"

def test_invalid_period_rejected():
    assert _period_month("not a period") is None

def test_supplement_single_month_accepted():
    d=supplement(["PMJJBY", "PMSBY"], ["August 2026", "2026-08"])
    assert _supplement_periods_match(d, transaction_month="2026-08")

def test_supplement_stale_month_rejected():
    d=supplement(["PMJJBY"], ["August 2026"])
    assert not _supplement_periods_match(d, transaction_month="2026-09")

def test_multi_month_requires_complete_coverage():
    d=supplement(["PMJJBY"], ["August 2026"])
    assert not _supplement_periods_match(d, transaction_months=["2026-08", "2026-09"])

def test_multi_month_complete_coverage_accepted():
    d=supplement(["PMJJBY", "PMSBY"], ["August 2026", "September 2026"])
    assert _supplement_periods_match(d, transaction_months=["2026-08", "2026-09"])

def test_social_security_rejects_unrelated_type():
    d=supplement(["PMJJBY", "PASSBOOK PRINTING"], ["2026-08", "2026-08"])
    assert not social_security_supplement_active(d, transaction_month="2026-08")

def test_passbook_accepts_only_passbook_type_and_period():
    d=supplement(["PASSBOOK PRINTING"], ["August 2026"])
    assert passbook_supplement_active(d, transaction_month="2026-08")

def test_pmjjby_rates_are_period_driven():
    assert [_pmjjby_rate_for_period(m) for m in ["August 2026", "September 2026", "December 2026", "March 2027"]] == [30.0, 22.5, 15.0, 7.5]


def test_combined_control_kpi_matches_validated_614_percent_baseline():
    from app.services.control_kpi import controlled_reconciliation_kpi
    matched, total, rate = controlled_reconciliation_kpi(2627, 4463, 333, 358)
    assert matched == 2960
    assert total == 4821
    assert rate == 61.40


def test_combined_control_kpi_does_not_change_primary_transaction_rate():
    from app.services.control_kpi import controlled_reconciliation_kpi
    _, _, combined_rate = controlled_reconciliation_kpi(2627, 4463, 333, 358)
    primary_rate = round(2627 / 4463 * 100, 2)
    assert primary_rate == 58.86
    assert combined_rate == 61.40


def test_combined_control_kpi_empty_population_is_unavailable():
    from app.services.control_kpi import controlled_reconciliation_kpi
    assert controlled_reconciliation_kpi(0, 0, 0, 0) == (0, 0, None)


def test_permanent_social_security_rates_cover_every_calendar_month():
    from app.services.social_security_rules import pmjjby_rate_for_period, pmsby_rate_for_period
    periods = [f"{m} 2026" for m in ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]]
    assert [pmjjby_rate_for_period(p) for p in periods] == [15.0, 15.0, 7.5, 7.5, 7.5, 30.0, 30.0, 30.0, 22.5, 22.5, 22.5, 15.0]
    assert [pmsby_rate_for_period(p) for p in periods] == [1.0] * 12


def test_pmjjby_premium_month_pairs_follow_sbi_source_rule():
    from app.services.social_security_rules import pmjjby_premium_is_valid_for_period
    assert pmjjby_premium_is_valid_for_period(436, "August 2026")
    assert pmjjby_premium_is_valid_for_period(342, "September 2026")
    assert pmjjby_premium_is_valid_for_period(228, "January 2027")
    assert pmjjby_premium_is_valid_for_period(114, "April 2027")
    assert not pmjjby_premium_is_valid_for_period(436, "September 2026")
    assert not pmjjby_premium_is_valid_for_period(342, "August 2026")
    assert not pmjjby_premium_is_valid_for_period(114, "Unknown period")


def test_count_kpi_keeps_missing_bc_groups_in_denominator_and_never_calls_missing_variance_match():
    import pandas as pd
    from app.api.dashboard import _count_control_masks

    frame = pd.DataFrame({
        "successful_transactions": [10, 7, 3, 5],
        "measurement_type": ["TRANSACTION_COUNT"] * 4,
        "report_base": [10, 8, None, 5],
        "count_variance": [0, -1, None, None],
    })
    control, matched, mismatch, missing_bc, missing_variance, _, _ = _count_control_masks(frame)
    assert int(control.sum()) == 4
    assert int(matched.sum()) == 1
    assert int(mismatch.sum()) == 3
    assert int(missing_bc.sum()) == 1
    assert int(missing_variance.sum()) == 1
    assert round(int(matched.sum()) / int(control.sum()) * 100, 2) == 25.0


def test_count_kpi_excludes_non_count_measurements_from_count_denominator():
    import pandas as pd
    from app.api.dashboard import _count_control_masks

    frame = pd.DataFrame({
        "successful_transactions": [10, 1, 1],
        "measurement_type": ["TRANSACTION_COUNT", "AMOUNT_BASED", "UNCLASSIFIED"],
        "report_base": [10, 1, 1],
        "count_variance": [0, 0, 0],
    })
    control, matched, mismatch, *_ = _count_control_masks(frame)
    assert int(control.sum()) == 1
    assert int(matched.sum()) == 1
    assert int(mismatch.sum()) == 0
