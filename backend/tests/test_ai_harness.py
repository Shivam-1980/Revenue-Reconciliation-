import pandas as pd
from app.services.ai_harness import investigate_result

def test_harness_returns_evidence_without_mutating_financials():
    df = pd.DataFrame([{"csp_id":"C1","transaction_type":"IMPS FUND TRANSFER","successful_transactions":2,"report_base":3,"count_variance":1,"expected_commission":10.0,"actual_commission":12.0,"financial_gap":2.0,"reconciliation_status":"SOURCE_COUNT_DIFFERENCE","exception_flag":True,"settlement_rule_approved":True}])
    before = df.copy(deep=True)
    report = investigate_result(df, {"period":"2026-08"})
    assert report["exception_groups"] == 1
    assert report["cases_returned"] == 1
    assert report["cases"][0]["decision"] == "INVESTIGATE"
    assert report["cases"][0]["financial_values_modified"] is False
    pd.testing.assert_frame_equal(df, before)

def test_harness_empty_exceptions_is_valid():
    df = pd.DataFrame([{"reconciliation_status":"MATCH","exception_flag":False}])
    report = investigate_result(df)
    assert report["exception_groups"] == 0
    assert report["cases"] == []


def test_phase1_tool_catalog_is_allowlisted_and_read_only():
    from app.services.ai_harness import TOOL_CATALOG, run_tool, HARNESS_VERSION
    assert HARNESS_VERSION == "2.0.0-phase2-investigation-agent"
    names = {item["name"] for item in TOOL_CATALOG}
    assert names == {"validate_upload", "resolve_csp_identity", "calculate_expected_commission", "reconcile_period", "explain_variance", "calculate_kpi"}
    try:
        run_tool("delete_rule", {})
    except ValueError as exc:
        assert "Unknown tool" in str(exc)
    else:
        raise AssertionError("Unlisted tool must be rejected")


def test_phase1_explain_variance_requires_a_filter():
    from app.services.ai_harness import run_tool
    try:
        run_tool("explain_variance", {})
    except ValueError as exc:
        assert "Provide csp_id and/or transaction_type" in str(exc)
    else:
        raise AssertionError("Variance tool must require a scoped query")


def test_phase2_agent_prioritizes_rule_uncertainty_and_financial_gap_without_mutation():
    from app.services.ai_harness import run_investigation_agent
    df = pd.DataFrame([
        {"csp_id":"C1","transaction_type":"TYPE A","successful_transactions":2,"report_base":3,"count_variance":1,"expected_commission":100.0,"actual_commission":0.0,"financial_gap":100.0,"reconciliation_status":"SOURCE_COUNT_DIFFERENCE","exception_flag":True,"settlement_rule_approved":True},
        {"csp_id":"C2","transaction_type":"TYPE B","expected_commission":500.0,"actual_commission":0.0,"financial_gap":500.0,"reconciliation_status":"RATE_MASTER_MISSING","exception_flag":True,"settlement_rule_approved":False},
        {"csp_id":"C3","transaction_type":"TYPE C","reconciliation_status":"Matched","exception_flag":False}
    ])
    before = df.copy(deep=True)
    report = run_investigation_agent(df, {"period":"2026-08"}, limit=10)
    assert report["mode"] == "phase2-deterministic-investigation-agent"
    assert report["cases_returned"] == 2
    assert report["cases"][0]["csp_id"] == "C2"
    assert report["cases"][0]["priority_score"] >= report["cases"][1]["priority_score"]
    assert all(c["approval_required"] and not c["financial_values_modified"] for c in report["cases"])
    assert report["agent_summary"]["tools_executed_automatically"] == []
    pd.testing.assert_frame_equal(df, before)


def test_phase2_agent_is_deterministic_and_bounded():
    from app.services.ai_harness import run_investigation_agent
    df = pd.DataFrame([{"csp_id":f"C{i}","transaction_type":"TYPE","financial_gap":i,"reconciliation_status":"Shortfall","exception_flag":True} for i in range(12)])
    a = run_investigation_agent(df, {"period":"2026-08"}, limit=5)
    b = run_investigation_agent(df, {"period":"2026-08"}, limit=5)
    assert len(a["cases"]) == 5
    assert [(c["case_id"],c["priority_score"]) for c in a["cases"]] == [(c["case_id"],c["priority_score"]) for c in b["cases"]]
