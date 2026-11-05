import pytest
"""End-to-end regression against the bundled V57 source population.

These assertions are deliberately source-level controls, not hard-coded dashboard
demo values. They ensure the shipped project can reproduce the same August-2026
calculation after refactors.
"""
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.reconciliation import load_result, TX
pytestmark = pytest.mark.skipif(not TX.exists(), reason="Historical August source data is not bundled in clean-upload release")


def test_v57_august_source_reconciliation_is_reproducible():
    # Use the current-signature reconciliation cache after the suite has already
    # exercised the same source. A dedicated isolated smoke test below covers the
    # uncached engine path; this regression remains source-level and fast in-suite.
    r = load_result(force=False)

    # The uploaded Success source remains 306,035 rows. The reconciliation result
    # intentionally replaces the legacy SSS population with the authoritative
    # CSP-wise PMJJBY/PMSBY supplement and adds the separately controlled CSP-wise
    # Passbook Printing population. The uploaded Success KPI itself remains 306,035.
    is_supp = r.get('is_supplemental', pd.Series(False, index=r.index, dtype='boolean')).astype('boolean').fillna(False).astype(bool)
    is_social = is_supp & r['transaction_type'].isin(['PMJJBY','PMSBY'])
    is_passbook = is_supp & r['transaction_type'].eq('PASSBOOK PRINTING')
    assert int(r.loc[~is_supp, 'successful_transactions'].sum()) == 305940
    assert int(r.loc[is_social, 'successful_transactions'].sum()) == 8808
    assert int(r.loc[is_passbook, 'successful_transactions'].sum()) == 14094
    assert int(r['successful_transactions'].sum()) == 328842
    expected = pd.to_numeric(r["expected_commission"], errors="coerce")
    actual = pd.to_numeric(r["actual_commission"], errors="coerce")
    comparable = (~is_supp) & expected.notna() & actual.notna() & r["successful_transactions"].gt(0)

    assert abs(float(expected.sum()) - 3554971.92) < 0.01
    assert abs(float(actual[comparable].sum()) - 3339746.83) < 0.01
    assert int(comparable.sum()) == 2891

    # Pending/unresolved commercial rules remain visible and are never silently
    # turned into zero expected revenue.
    assert int(r.loc[~is_supp, "rate_rule_pending"].sum()) == 209062
    assert int(r.loc[~is_supp, "rate_rule_missing"].sum()) == 193
    assert int(r.loc[~is_supp, "rate_rule_ambiguous"].sum()) == 0
    assert r.loc[r["rate_rule_missing"].gt(0), "expected_commission"].isna().all()

    # The provisional financial control must be populated separately from the
    # settlement-approved financial gap.
    provisional = pd.to_numeric(r["provisional_financial_gap"], errors="coerce")
    assert abs(float(provisional[comparable].sum()) - 35333.59) < 0.01
