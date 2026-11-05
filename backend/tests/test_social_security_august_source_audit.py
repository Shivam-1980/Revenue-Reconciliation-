import pandas as pd
from pathlib import Path
import pytest

BACKEND = Path(__file__).resolve().parents[1]
SUPP = BACKEND / "app" / "data" / "supplemental"
pytestmark = pytest.mark.skipif(not (SUPP / "latest_social_security_counts.csv").exists(), reason="August supplemental files are intentionally not bundled; run these audit checks with uploaded August fixtures")

def test_august_social_security_supplement_contains_only_exact_csp_ids_and_period():
    d = pd.read_csv(SUPP / "latest_social_security_counts.csv", dtype=str).fillna("")
    assert set(d["period"]) == {"2026-08"}
    assert set(d["transaction_type"]) == {"PMJJBY", "PMSBY"}
    assert d["csp_id"].str.fullmatch(r"1A85\d{4}").all()
    assert not d.duplicated(["csp_id", "transaction_type", "period"]).any()
    d["count"] = pd.to_numeric(d["count"])
    totals = d.groupby("transaction_type")["count"].sum().to_dict()
    assert totals == {"PMJJBY": 3414, "PMSBY": 5394}
    assert (d["csp_id"] == "1A859001").sum() == 2

def test_malformed_source_csp_rows_are_preserved_as_exceptions_not_fuzzy_matched():
    d = pd.read_csv(SUPP / "latest_social_security_counts_exceptions.csv", dtype=str).fillna("")
    assert set(d["raw_csp_code"]) >= {"f", ""}
    assert "Gursewak Gursewak" not in set(d["raw_csp_code"])
    nonzero = d[pd.to_numeric(d["count"]) > 0]
    # Gursewak's three August supplementary rows are now resolved by the exact
    # approved alias to CSP 1A859001; no positive enrollment remains unresolved.
    assert len(nonzero) == 0
    assert int(pd.to_numeric(d["indicative_commission_not_approved"]).sum()) == 0
    assert d["resolution"].str.contains("do not fuzzy-match", case=False).all()

def test_permanent_monthly_rates_match_august_rule():
    import sys
    sys.path.insert(0, str(BACKEND))
    from app.services.social_security_rules import pmjjby_rate_for_period, pmsby_rate_for_period
    assert pmjjby_rate_for_period("2026-08") == 30.0
    assert pmsby_rate_for_period("2026-08") == 1.0

def test_august_aggregate_uses_exact_csp_ids_and_keeps_unresolved_amount_separate():
    import sys
    sys.path.insert(0, str(BACKEND))
    from app.services.reconciliation_engine import aggregate_social_security_reconciliation
    bc_path = BACKEND.parent / "docs" / "validation" / "PMJJBY_PMSBY_August_2026_BC_Data_embedded_from_prior_reconciliation.csv"
    bc = pd.read_csv(bc_path, dtype={"CSP Code": str})
    r = bc.rename(columns={"CSP Code": "csp_id", "Scheme": "transaction_type", "Txns": "report_base", "Commission": "actual_commission"})
    r["join_type"] = r["transaction_type"]
    r["is_supplemental"] = True
    result = aggregate_social_security_reconciliation(r, transaction_month="2026-08")
    assert result["total"]["source_transactions"] == 8808
    assert result["total"]["bc_transactions"] == 8825
    assert result["total"]["expected_commission"] == 107814.0
    assert result["total"]["actual_commission"] == 107889.0
    assert result["total"]["commission_difference_bc_minus_expected"] == 75.0
    # Exact approved Gursewak -> 1A859001 mapping resolves the 16 enrollments;
    # no positive-count rows remain excluded from the approved CSP-level total.
    assert result["source_data_quality"]["excluded_enrollment_count"] == 0
    assert result["source_data_quality"]["indicative_commission_not_approved"] == 0.0
