import json
from pathlib import Path
import pytest
from fastapi import HTTPException
from app.api import reconciliation_history as history


def test_period_key_uses_transaction_source_month():
    key, label = history._period_key({"transactions": {"period_start": "2026-08-01", "period_end": "2026-08-31"}})
    assert key == "2026-08"
    assert label == "2026-08"


def test_period_key_preserves_multi_month_range_without_mislabeling():
    key, label = history._period_key({"transactions": {"period_start": "2026-08-01", "period_end": "2026-09-30"}})
    assert key == "2026-08_to_2026-09"
    assert label == "2026-08 to 2026-09"


def test_period_key_rejects_missing_period_metadata():
    with pytest.raises(HTTPException) as exc:
        history._period_key({"transactions": {}})
    assert exc.value.status_code == 400


def test_history_snapshot_survives_current_workspace_changes(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    snapshot = {"period_key": "2026-08", "period_label": "2026-08", "saved_at": "2026-10-27T00:00:00+00:00",
                "summary": {"expected_commission": 1200.0, "actual_commission": 1100.0}, "csp": [], "transaction_types": [], "exceptions": []}
    (tmp_path / "2026-08.json").write_text(json.dumps(snapshot), encoding="utf-8")
    listed = history.list_reconciliation_history()
    assert listed["count"] == 1
    assert listed["periods"][0]["period_key"] == "2026-08"
    assert history.get_reconciliation_history("2026-08")["summary"]["expected_commission"] == 1200.0


def test_history_rejects_path_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc:
        history.get_reconciliation_history("../secrets")
    assert exc.value.status_code == 400



def test_legacy_audit_runs_are_listed_when_no_snapshot_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(history, "_legacy_audit_rows", lambda: [{
        "period_key": "2026-09", "period_label": "2026-09", "saved_at": "2026-10-02T00:00:00+00:00",
        "source_filenames": {"transactions": "Successful_Sep-26.xlsx"}, "successful_transactions": 123,
        "expected_commission": 1200.0, "actual_commission": 1100.0, "variance": -100.0,
        "legacy_audit_summary_only": True, "_run": {"run_id": "REC-OLD", "status": "COMPLETED"}
    }])
    result = history.list_reconciliation_history()
    assert result["count"] == 1
    assert result["periods"][0]["period_key"] == "2026-09"
    assert result["periods"][0]["legacy_audit_summary_only"] is True


def test_legacy_snapshot_does_not_fabricate_detail(monkeypatch):
    monkeypatch.setattr(history, "_legacy_audit_rows", lambda: [{
        "period_key": "2026-09", "period_label": "2026-09", "saved_at": "2026-10-02T00:00:00+00:00",
        "source_filenames": {}, "_run": {"run_id": "REC-OLD", "status": "COMPLETED", "successful_transactions": 123,
        "reconciliation_groups": 8, "matched_groups": 5, "comparable_expected_commission": 1200.0,
        "actual_comparable_commission": 1100.0, "comparable_variance": -100.0}
    }])
    snap = history._legacy_snapshot("2026-09")
    assert snap["legacy_audit_summary_only"] is True
    assert snap["summary"]["historical_detail_level"] == "summary_only"
    assert snap["csp"] == [] and snap["transaction_types"] == []
    assert snap["summary"]["actual_comparable_commission"] == 1100.0



def test_period_key_falls_back_to_normalized_transaction_csv(monkeypatch, tmp_path):
    csv_path = tmp_path / "latest_transactions.csv"
    csv_path.write_text("transaction_date,transaction_type\n2026-09-01,Money Transfer\n2026-09-30,Money Transfer\n", encoding="utf-8")
    key, label = history._period_key({"transactions": {}}, csv_path)
    assert key == "2026-09"
    assert label == "2026-09"


def test_snapshot_detail_level_requires_full_reconciliation_payload():
    full = {"summary": {}, "csp": [], "transaction_types": [], "exceptions": [],
            "reconciliation_rows": [], "csp_type": [], "successful_transaction_types": {}, "supplemental": {}}
    assert history._snapshot_detail_level(full) == "full"
    assert history._snapshot_detail_level({"summary": {"historical_detail_level": "summary_only"}}) == "summary_only"
    assert history._snapshot_detail_level({"summary": {}, "csp": [], "transaction_types": [], "exceptions": []}) == "partial"


def test_history_listing_exposes_detail_level_and_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    snapshot = {"period_key": "2026-10", "period_label": "2026-10", "saved_at": "2026-10-27T00:00:00+00:00",
                "summary": {}, "csp": [{"csp_id": "C1"}], "transaction_types": [], "exceptions": [],
                "reconciliation_rows": [{"csp_id": "C1", "transaction_type": "MONEY TRANSFER"}],
                "csp_type": [], "successful_transaction_types": {}, "supplemental": {},
                "detail_counts": {"csp": 1, "reconciliation_rows": 1}}
    (tmp_path / "2026-10.json").write_text(json.dumps(snapshot), encoding="utf-8")
    row = history.list_reconciliation_history()["periods"][0]
    assert row["detail_level"] == "full"
    assert row["detail_counts"]["reconciliation_rows"] == 1
    assert row["legacy_audit_summary_only"] is False
