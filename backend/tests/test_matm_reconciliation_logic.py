import pandas as pd
import app.api.upload as upload


def test_matm_monthly_cap_applied_after_csp_period_aggregation_and_count_mismatch_separate(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    commission_dir = tmp_path / "commission"
    tx_dir = tmp_path / "transactions"
    supplemental.mkdir()
    commission_dir.mkdir()
    tx_dir.mkdir()

    pd.DataFrame([
        {"period": "2026-08", "csp_id": "1A850001", "csp_name": "CSP One", "matm_transaction_count": 200},
        {"period": "2026-08", "csp_id": "1A850001", "csp_name": "CSP One", "matm_transaction_count": 200},
        {"period": "2026-08", "csp_id": "1A850002", "csp_name": "CSP Two", "matm_transaction_count": 5},
        {"period": "2026-08", "csp_id": "1A850003", "csp_name": "CSP Three", "matm_transaction_count": 0},
    ]).to_csv(supplemental / "latest_matm_incentive_counts.csv", index=False)

    pd.DataFrame([
        {"csp_id": "1A850001", "transaction_type": "MATM CASH TRANSACTIONS INCENTIVE", "report_base": 350, "actual_commission": 1000},
    ]).to_csv(commission_dir / "latest_commission.csv", index=False)

    monkeypatch.setattr(upload, "MATM_COUNTS", supplemental / "latest_matm_incentive_counts.csv")
    monkeypatch.setattr(upload, "CM", commission_dir)
    monkeypatch.setattr(upload, "TX", tx_dir)

    result = upload.matm_incentive_reconciliation()
    assert result["status"] == "READY"
    summary = result["summary"]
    # Duplicate source rows for the same CSP/month aggregate to 400, then cap once at ₹1,000.
    assert summary["expected_total"] == 1015.0
    assert summary["actual_total"] == 1000.0
    # The commission is matched for CSP One even though its bank transaction count differs.
    row = next(r for r in result["rows"] if r["csp_id"] == "1A850001")
    assert row["status"] == "MATCHED"
    assert row["count_variance_bank_minus_source"] == -50
    assert row["count_status"] == "COUNT MISMATCH"
    assert summary["count_mismatches"] == 1
    assert summary["count_matched"] == 0
    assert summary["short_paid"] == 1
    assert summary["no_activity"] == 1


def test_matm_reconciliation_rejects_multiple_source_months_against_one_bc_report(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    commission_dir = tmp_path / "commission"
    tx_dir = tmp_path / "transactions"
    supplemental.mkdir()
    commission_dir.mkdir()
    tx_dir.mkdir()

    pd.DataFrame([
        {"period": "2026-07", "csp_id": "1A850001", "csp_name": "CSP One", "matm_transaction_count": 400},
        {"period": "2026-08", "csp_id": "1A850001", "csp_name": "CSP One", "matm_transaction_count": 400},
    ]).to_csv(supplemental / "latest_matm_incentive_counts.csv", index=False)
    pd.DataFrame([
        {"csp_id": "1A850001", "transaction_type": "MATM CASH TRANSACTIONS INCENTIVE", "report_base": 700, "actual_commission": 1000},
    ]).to_csv(commission_dir / "latest_commission.csv", index=False)

    monkeypatch.setattr(upload, "MATM_COUNTS", supplemental / "latest_matm_incentive_counts.csv")
    monkeypatch.setattr(upload, "CM", commission_dir)
    monkeypatch.setattr(upload, "TX", tx_dir)

    result = upload.matm_incentive_reconciliation()
    assert result["available"] is False
    assert result["status"] == "SOURCE_PERIOD_AMBIGUOUS"


def test_matm_source_noncanonical_id_resolves_only_by_unique_current_bc_name(tmp_path, monkeypatch):
    supplemental = tmp_path / "supplemental"
    commission_dir = tmp_path / "commission"
    tx_dir = tmp_path / "transactions"
    supplemental.mkdir()
    commission_dir.mkdir()
    tx_dir.mkdir()
    pd.DataFrame([
        {"period": "2026-08", "csp_id": "OTHER ISSUE", "csp_name": "Sample Agent", "matm_transaction_count": 65},
    ]).to_csv(supplemental / "latest_matm_incentive_counts.csv", index=False)
    pd.DataFrame([
        {"csp_id": "1A859006", "csp_name": "SAMPLE  AGENT", "transaction_type": "MATM CASH TRANSACTIONS INCENTIVE", "report_base": 41, "actual_commission": 123},
    ]).to_csv(commission_dir / "latest_commission.csv", index=False)
    monkeypatch.setattr(upload, "MATM_COUNTS", supplemental / "latest_matm_incentive_counts.csv")
    monkeypatch.setattr(upload, "CM", commission_dir)
    monkeypatch.setattr(upload, "TX", tx_dir)

    result = upload.matm_incentive_reconciliation()
    row = result["rows"][0]
    assert row["csp_id"] == "1A859006"
    assert row["source_csp_id"] == "OTHER ISSUE"
    assert row["identity_resolution"] == "EXACT_UNIQUE_CURRENT_BC_NAME"
    assert row["expected_incentive"] == 195
    assert row["actual_commission"] == 123
    assert row["variance_actual_minus_expected"] == -72
    assert row["count_variance_bank_minus_source"] == -24
    assert row["count_status"] == "COUNT MISMATCH"
    assert row["status"] == "SHORT PAID"
