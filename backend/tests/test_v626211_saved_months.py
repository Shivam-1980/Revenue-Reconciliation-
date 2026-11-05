"""Reconciled months are saved in the database and restored without re-uploading (V62.6.211)."""
import json

import pytest

from app import database
from app.services import period_store
from test_v626207_database import db  # noqa: F401  (SQLite + PostgreSQL fixture)


@pytest.fixture
def ws(monkeypatch, tmp_path):
    data = tmp_path / "data"
    files = {
        "transactions/latest_transactions.csv": "transaction_id,csp_id,amount\nT1,1A850001,1000.50\n",
        "transactions/latest_transactions_raw.csv": "Reference Number,CSP Code,Amount\nT1,1A850001,1000.50\n",
        "commissions/latest_commission.csv": "csp_id,transaction_type,actual_commission\n1A850001,CASH WITHDRAWAL,5\n",
        "supplemental/latest_women_csp_roster.csv": "csp_id,csp_name,transaction_count\n1A859006,SAMPLE AGENT,573\n",
        "supplemental/latest_women_csp_roster_metadata.json": '{"period": "2026-08"}',
        "rural_csp/latest_rural_csp_master.csv": "csp_id,login_days\n1A850001,22\n",
        "rate_master/latest_rate_master.csv": "rule_id,rate\nTODAY,4.0\n",
    }
    for rel, text in files.items():
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        (data / rel).write_text(text, encoding="utf-8")
    (data / "upload_metadata.json").write_text(json.dumps({
        "transactions": {"filename": "Success Aug.xlsx", "period_start": "2026-08-01"},
        "rate_master": {"filename": "SBI rules", "version": "today"}}), encoding="utf-8")
    (data / "reconciliation_cache.csv").write_text("stale", encoding="utf-8")
    monkeypatch.setattr(period_store, "DATA", data)
    return data, files


def _clear_workspace(data):
    for sub in period_store.SOURCE_DIRS:
        for p in (data / sub).glob("*"):
            p.unlink()


def test_month_survives_restart_and_restores_byte_identical(db, ws):  # noqa: F811
    data, files = ws
    database.init_schema()
    saved = period_store.save_period("2026-08", "August 2026", "tester")
    assert saved["files"] == 7  # 6 source files + upload metadata; rate master excluded
    original = {rel: (data / rel).read_bytes() for rel in files}

    _clear_workspace(data)                              # what start.bat's clean start does
    assert not (data / "transactions/latest_transactions.csv").exists()
    assert "2026-08" in period_store.saved_periods()

    (data / "rate_master/latest_rate_master.csv").write_text("rule_id,rate\nTODAY,4.0\n", encoding="utf-8")
    meta = json.loads((data / "upload_metadata.json").read_text(encoding="utf-8"))
    meta["rate_master"] = {"filename": "SBI rules", "version": "newer-approved"}
    (data / "upload_metadata.json").write_text(json.dumps(meta), encoding="utf-8")

    result = period_store.restore_period("2026-08")
    assert result["files_restored"] == 6
    for rel, data_bytes in original.items():
        if not rel.startswith("rate_master/"):
            assert (data / rel).read_bytes() == data_bytes, rel
    restored_meta = json.loads((data / "upload_metadata.json").read_text(encoding="utf-8"))
    assert restored_meta["transactions"]["filename"] == "Success Aug.xlsx"
    assert restored_meta["rate_master"]["version"] == "newer-approved"   # current approved SBI rules kept
    assert not (data / "reconciliation_cache.csv").exists()              # forces a fresh calculation


def test_restore_replaces_other_month_files_and_resave_overwrites(db, ws):  # noqa: F811
    data, _ = ws
    database.init_schema()
    period_store.save_period("2026-08", "August 2026", "tester")
    (data / "supplemental/latest_tab_incentive_counts.csv").write_text("period,csp_id\n2026-09,1A850009\n", encoding="utf-8")
    period_store.restore_period("2026-08")
    assert not (data / "supplemental/latest_tab_incentive_counts.csv").exists()   # September file not mixed in
    (data / "commissions/latest_commission.csv").write_text("csp_id,transaction_type,actual_commission\n1A850001,X,9\n", encoding="utf-8")
    period_store.save_period("2026-08", "August 2026", "tester")
    assert len(period_store.saved_periods()) == 1
    _clear_workspace(data)
    period_store.restore_period("2026-08")
    assert "X,9" in (data / "commissions/latest_commission.csv").read_text(encoding="utf-8")


def test_unknown_month_and_missing_sources_are_reported(db, ws):  # noqa: F811
    data, _ = ws
    database.init_schema()
    with pytest.raises(KeyError):
        period_store.restore_period("2025-01")
    (data / "commissions/latest_commission.csv").unlink()
    with pytest.raises(ValueError):
        period_store.save_period("2026-08")


def test_restore_api_and_history_flag(db, ws):  # noqa: F811
    from fastapi.testclient import TestClient
    from app.main import app
    database.init_schema()
    period_store.save_period("2026-08", "August 2026", "tester")
    client = TestClient(app)
    periods = {p["period_key"]: p for p in client.get("/api/reconciliation/history").json()["periods"]}
    assert periods["2026-08"]["restorable"] is True
    r = client.post("/api/reconciliation/history/2026-08/restore")
    assert r.status_code == 200 and r.json()["restored"] is True and "Run reconciliation" in r.json()["message"]
    assert client.post("/api/reconciliation/history/2024-01/restore").status_code == 404


def test_uploaded_but_unreconciled_month_is_saved_once_and_resaved_only_when_files_change(db, ws):  # noqa: F811
    database.init_schema()
    data, files = ws
    first = period_store.save_period_if_changed("2026-08", "2026-08", "tester")
    assert first["saved"] is True and "2026-08" in period_store.saved_periods()
    assert period_store.save_period_if_changed("2026-08", "2026-08", "tester") == {"saved": False, "reason": "unchanged"}
    (data / "commissions/latest_commission.csv").write_text("csp_id,transaction_type,actual_commission\n1A850001,CASH WITHDRAWAL,6\n", encoding="utf-8")
    assert period_store.save_period_if_changed("2026-08", "2026-08", "tester")["saved"] is True       # a replaced file is stored again
    (data / "supplemental/latest_women_csp_roster.csv").write_text("csp_id,csp_name,transaction_count\n1A859006,SAMPLE AGENT,574\n", encoding="utf-8")
    assert period_store.save_period_if_changed("2026-08", "2026-08", "tester")["saved"] is True       # so is a new supporting file
    _clear_workspace(data)                                                                            # app restart
    period_store.restore_period("2026-08")
    assert (data / "commissions/latest_commission.csv").read_text(encoding="utf-8").endswith("CASH WITHDRAWAL,6\n")
    assert (data / "supplemental/latest_women_csp_roster.csv").read_text(encoding="utf-8").endswith("574\n")


def test_nothing_is_saved_until_both_required_files_are_present(db, ws):  # noqa: F811
    database.init_schema()
    data, _ = ws
    (data / "commissions/latest_commission.csv").unlink()
    out = period_store.save_period_if_changed("2026-08", "2026-08", "tester")
    assert out["saved"] is False and "2026-08" not in period_store.saved_periods()


def test_database_sync_never_fails_when_the_month_cannot_be_determined(monkeypatch):
    from app.services import db_sync
    out = db_sync.save_month_files("tester", {"transactions": None})
    assert out["saved"] is False and out["reason"]
