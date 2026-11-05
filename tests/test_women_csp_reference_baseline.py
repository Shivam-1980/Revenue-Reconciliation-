import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_release_has_no_preloaded_period_transaction_or_incentive_data():
    data = ROOT / "backend" / "app" / "data"
    meta = json.loads((data / "upload_metadata.json").read_text(encoding="utf-8"))
    for key in ("transactions", "commission", "csp_geography", "rural_csp",
                "social_security_counts", "passbook_printing_counts", "dfs_incentive",
                "women_csp_roster", "tab_incentive", "loan_lead_generation"):
        assert meta.get(key) is None, key
    assert meta.get("active_batch_id") is None
    assert not (data / "transactions" / "latest_transactions.csv").exists()
    assert not (data / "commissions" / "latest_commission.csv").exists()
    assert not (data / "supplemental" / "latest_tab_incentive_counts.csv").exists()
    assert not (ROOT / "sample_uploads").exists()
    assert (data / "expected_commission_rule" / "latest.xlsx").exists()
    assert (data / "rate_master" / "latest_rate_master.csv").exists()
