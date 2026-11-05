from pathlib import Path


def test_historical_dashboard_restores_saved_loan_lead_control():
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "src" / "main.jsx"
    source = frontend.read_text(encoding="utf-8")
    assert "setLoanLeadCommission(extra.loan_lead_commission || null)" in source
    assert "setSelectedHistory(periodKey); setViewingHistory(true)" in source


def test_monthly_history_snapshot_persists_loan_lead_supplemental_result():
    history_api = Path(__file__).resolve().parents[1] / "app" / "api" / "reconciliation_history.py"
    source = history_api.read_text(encoding="utf-8")
    assert '"loan_lead_commission", upload.loan_lead_generation_reconciliation' in source
    assert '"supplemental": supplemental' in source
