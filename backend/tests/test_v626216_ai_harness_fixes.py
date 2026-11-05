"""AI harness faults found when it was run on the real September result (V62.6.216)."""
import pandas as pd

from app.services import ai_harness as ah


def _frame(n_filler=600):
    rows = [{"csp_id": f"F{i}", "transaction_type": "T", "reconciliation_status": "SOURCE_COUNT_DIFFERENCE", "exception_flag": True,
             "count_variance": 1.0, "financial_gap": 0.0, "expected_commission": 10.0, "actual_commission": 10.0} for i in range(n_filler)]
    # an urgent case that sits far down the table: big gap, no rule approval, expected but nothing paid
    rows.append({"csp_id": "URGENT", "transaction_type": "T", "reconciliation_status": "RATE_MASTER_MISSING", "exception_flag": True,
                 "count_variance": 50.0, "financial_gap": 90000.0, "expected_commission": 5000.0, "actual_commission": 0.0, "settlement_rule_approved": False})
    return pd.DataFrame(rows)


def test_an_urgent_case_far_down_the_table_reaches_the_queue():
    rep = ah.run_investigation_agent(_frame(), {}, limit=5)
    assert rep["cases"][0]["csp_id"] == "URGENT" and rep["cases"][0]["queue_rank"] == 1
    assert rep["cases_returned"] == 5
    assert sum(rep["agent_summary"]["priority_counts_all_exceptions"].values()) == 601      # every exception was ranked


def test_evidence_required_is_explained_and_not_treated_as_low_priority():
    df = pd.DataFrame([{"csp_id": "C", "transaction_type": "INITIAL DEPOSIT", "reconciliation_status": "EVIDENCE_REQUIRED", "exception_flag": True}])
    case = ah.run_investigation_agent(df, {}, limit=5)["cases"][0]
    assert "evidence" in case["root_cause_hypothesis"].lower() and case["priority_score"] >= 36


def test_reconcile_period_counts_the_real_match_label(monkeypatch):
    df = pd.DataFrame({"csp_id": list("abcd"), "reconciliation_status": ["MATCH", "MATCH", "Excess", "BC_ONLY_ACTIVITY"]})
    monkeypatch.setattr(ah, "_current_result", lambda force=False: df)
    import app.api.dashboard as dash
    monkeypatch.setattr(dash, "summary", lambda: {"count_control_groups": 4, "count_matched_groups": 2, "reconciliation_rate": 50.0})
    out = ah.run_tool("reconcile_period")
    assert out["matched_groups"] == 2 and out["match_rate_percent"] == 50.0 and out["status_counts"]["MATCH"] == 2


def test_kpi_tool_only_asks_for_fields_the_dashboard_has_and_names_what_is_missing(monkeypatch):
    import app.api.dashboard as dash
    monkeypatch.setattr(dash, "summary", lambda: {"reconciliation_rate": 65.0, "all_source_control_rate": 69.12})
    out = ah.run_tool("calculate_kpi")
    assert out["kpis"] == {"reconciliation_rate": 65.0, "all_source_control_rate": 69.12}
    assert "matm_control_groups" not in out["not_available"] and "all_source_control_groups" in out["not_available"]
    assert "transaction_only_reconciliation_rate" not in out["not_available"]      # the made-up field names are gone


def test_validate_upload_reads_the_metadata_of_supplemental_files(monkeypatch, tmp_path):
    import json
    from app.api import upload as upload_api
    (tmp_path / "latest_dfs_incentive_counts.csv").write_text("a\n1\n")
    (tmp_path / "latest_dfs_incentive_metadata.json").write_text(json.dumps({"filename": "DFS.xlsx", "rows": 158, "periods": ["2026-09"]}))
    monkeypatch.setattr(upload_api, "SUPPLEMENTAL", tmp_path); monkeypatch.setattr(upload_api, "DFS_COUNTS", tmp_path / "latest_dfs_incentive_counts.csv")
    src = ah.run_tool("validate_upload", {"kind": "dfs_incentive"})["sources"][0]
    assert src["uploaded"] and src["valid"] and src["rows"] == 158 and src["filename"] == "DFS.xlsx" and src["period_start"] == "2026-09"
