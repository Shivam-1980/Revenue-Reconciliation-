from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = (ROOT.parent / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")


def test_historical_snapshot_restores_passbook_and_women_supplemental_results():
    assert 'setPassbookCommission(extra.passbook_printing || null)' in FRONTEND
    assert 'historicalWomenCspIncentive={viewingHistory ? (summary?.historical_snapshot ? (summary?.supplemental?.women_csp_incentive || null) : null) : null}' in FRONTEND
    assert '<PassbookPrintingPanel data={passbookCommission} viewingHistory={viewingHistory} />' in FRONTEND


def test_historical_supplemental_panels_do_not_fetch_active_period_data():
    assert 'function DfsReconciliationPanel({historicalData=null,viewingHistory=false})' in FRONTEND
    assert 'function WomenCspIncentivePanel({historicalData=null,viewingHistory=false})' in FRONTEND
    assert 'function MatmIncentivePanel({historicalData=null,viewingHistory=false})' in FRONTEND
    assert 'const shownData = viewingHistory ? historicalData : data;' in FRONTEND
    assert 'const shownData=viewingHistory ? historicalData : data;' in FRONTEND
    assert 'if(viewingHistory)return;let live=true;fetch(`${API_BASE}/api/upload/matm-incentive/reconciliation`' in FRONTEND


def test_historical_snapshot_payload_includes_supplemental_controls():
    history = (ROOT / "app" / "api" / "reconciliation_history.py").read_text(encoding="utf-8")
    assert '("passbook_printing", reconciliation.passbook_printing)' in history
    assert '("women_csp_incentive", upload.women_csp_incentive_reconciliation)' in history
    assert '("dfs_commission", upload.dfs_incentive_reconciliation)' in history
    assert '("matm_commission", upload.matm_incentive_reconciliation)' in history
    assert '("loan_lead_commission", upload.loan_lead_generation_reconciliation)' in history
