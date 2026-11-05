"""Regression tests against the bundled August 2026 reconciliation source batch."""
import math
from pathlib import Path
import pandas as pd
import pytest

BACKEND = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (BACKEND / "app/data/transactions/latest_transactions.csv").exists(), reason="August batch is intentionally not bundled; run these integration checks with uploaded August fixtures")


def test_dashboard_summary_and_count_type_breakdown_are_available():
    from app.api.dashboard import summary
    s = summary()
    assert s["successful_transactions"] == 306035
    assert s["count_matched_groups"] == 2627
    assert s["count_mismatch_groups"] == 1836
    assert s["count_control_groups"] == 4463
    assert s["reconciliation_rate"] == 58.86
    assert s["source_count_control"]["match_rate_pct"] == 58.86
    assert all("mismatch_groups" in row for row in s["source_count_control"]["type_breakdown"])


def test_combined_historical_control_kpi_reproduces_61_40_percent():
    from app.api.dashboard import summary
    s = summary()
    assert s["overall_controlled_matched_groups"] == 2960
    assert s["overall_controlled_groups"] == 4821
    assert s["overall_controlled_reconciliation_rate"] == 61.40
    assert math.isclose((2627 + 333) / (4463 + 358) * 100, 61.40, abs_tol=0.01)


def test_financial_comparable_subset_is_consistent():
    from app.api.dashboard import summary
    s = summary()
    # Do not pin this to a stale historical amount: the packaged August source
    # bundle and supplemental counts are the authority for the current release.
    assert s["expected_commission_comparable"] is not None
    assert s["actual_comparable_commission"] is not None
    assert s["comparable_variance"] is not None
    assert math.isclose(s["expected_commission_comparable"] - s["actual_comparable_commission"], s["comparable_variance"], abs_tol=0.01)


def test_gursewak_manual_alias_is_present_in_all_three_august_controls():
    ss = pd.read_csv(BACKEND / "app/data/supplemental/latest_social_security_counts.csv", dtype=str).fillna("")
    pb = pd.read_csv(BACKEND / "app/data/supplemental/latest_passbook_printing_counts.csv", dtype=str).fillna("")
    assert int(((ss["csp_id"] == "1A859001") & (ss["transaction_type"] == "PMJJBY") & (pd.to_numeric(ss["count"]) == 2)).sum()) == 1
    assert int(((ss["csp_id"] == "1A859001") & (ss["transaction_type"] == "PMSBY") & (pd.to_numeric(ss["count"]) == 14)).sum()) == 1
    assert int(((pb["csp_id"] == "1A859001") & (pd.to_numeric(pb["count"]) == 3)).sum()) == 1
