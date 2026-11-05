"""The release packager must exclude runtime state and keep permanent masters."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("package_release", ROOT / "tools" / "package_release.py")
package_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_release)

excluded = package_release.is_excluded


def test_runtime_artifacts_are_excluded():
    for rel in (
        ".eko_reconciliation_initialized_version",
        ".pytest_cache/v/cache/nodeids",
        "backend/app/__pycache__/main.cpython-313.pyc",
        "backend/data/platform.sqlite3",
        "frontend/node_modules/vite/bin/vite.js",
        "frontend/dist/index.html",
        "build_audit_report.py",
        "backend_runtime.log",
        "backend/data/local_secrets.json",
        "backend/data/dev_outbox/1700000000_abc.txt",
        "backend/.env",
        "backend/data/other.sqlite3",
        "backend/data/platform.sqlite3-wal",
        "backend/data/platform.sqlite3-shm",
    ):
        assert excluded(Path(rel)), rel


def test_period_data_and_outputs_are_excluded():
    for rel in (
        "backend/app/data/transactions/latest_transactions.csv",
        "backend/app/data/commissions/latest_commission_raw.csv",
        "backend/app/data/reconciliation_history/2026-08.json",
        "backend/app/data/supplemental/latest_women_csp_roster.csv",
        "backend/app/data/reconciliation_cache.csv",
        "backend/app/data/audit/run_log.csv",
    ):
        assert excluded(Path(rel)), rel


def test_permanent_masters_and_sources_are_kept():
    for rel in (
        "backend/app/data/expected_commission_rule/latest.xlsx",
        "backend/app/data/rate_master/latest_rate_master.csv",
        "backend/app/data/rate_master/approved_rule_master_reference.csv",
        "backend/app/data/transaction_type_mapping_master.csv",
        "backend/app/data/rural_csp/rural_transaction_type_mapping.csv",
        "backend/app/data/upload_metadata.json",
        "backend/app/main.py",
        "frontend/package-lock.json",
        "start.bat",
    ):
        assert not excluded(Path(rel)), rel


def test_windows_batch_files_use_crlf():
    # cmd.exe can misread goto/call labels in LF-only batch files.
    for bat in ROOT.rglob("*.bat"):
        if "node_modules" in bat.parts:
            continue
        data = bat.read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n"), f"{bat.relative_to(ROOT)} must use CRLF line endings"
