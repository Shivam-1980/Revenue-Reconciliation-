import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_tenant_reconciliation_and_report_export_worker(tmp_path, monkeypatch):
    from app.services import platform_jobs, platform_worker
    monkeypatch.setattr(platform_jobs, "DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(platform_worker, "WORKSPACE_ROOT", (tmp_path / "tenants").resolve())
    org = platform_worker.WORKSPACE_ROOT / "org_test"
    org.mkdir(parents=True)
    pd.DataFrame([{
        "transaction_id": "t1", "csp_id": "c1", "transaction_type": "MONEY TRANSFER",
        "amount": 1000, "transaction_date": "2026-09-01", "status": "SUCCESS"
    }]).to_csv(org / "transactions.csv", index=False)
    pd.DataFrame([{
        "csp_id": "c1", "transaction_type": "MONEY TRANSFER",
        "transaction_count": 1, "actual_commission": 5
    }]).to_csv(org / "commission.csv", index=False)

    job = platform_jobs.enqueue("org_test", "user1", "reconciliation", {
        "source": "tenant_workspace",
        "relative_paths": {"transactions": "transactions.csv", "commission": "commission.csv",
                          "rate_master": "rate_master.csv", "result": "reconciliation_result.csv"}
    })
    assert platform_worker.process_one() is True
    finished = platform_jobs.get_job(job["id"], "org_test")
    assert finished["status"] == "succeeded", finished.get("error")
    assert finished["result"]["period_agnostic"] is True
    assert (org / "reconciliation_result.csv").is_file()

    export = platform_jobs.enqueue("org_test", "user1", "report_export", {
        "source": "tenant_workspace", "relative_path": "reconciliation_result.csv",
        "output_path": "reconciliation_report.xlsx"
    })
    assert platform_worker.process_one() is True
    exported = platform_jobs.get_job(export["id"], "org_test")
    assert exported["status"] == "succeeded", exported.get("error")
    assert (org / "reconciliation_report.xlsx").is_file()


def test_tenant_worker_rejects_cross_workspace_path(tmp_path, monkeypatch):
    from app.services import platform_jobs, platform_worker
    monkeypatch.setattr(platform_jobs, "DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(platform_worker, "WORKSPACE_ROOT", (tmp_path / "tenants").resolve())
    job = platform_jobs.enqueue("org_test", "user1", "file_validation", {"relative_path": "../../outside.csv"})
    assert platform_worker.process_one() is True
    finished = platform_jobs.get_job(job["id"], "org_test")
    assert finished["status"] == "failed"
    assert "escapes" in finished["error"]
