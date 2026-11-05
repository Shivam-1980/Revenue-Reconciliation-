from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_dfs_reconciliation_uses_normalized_actual_commission_column():
    source = (ROOT / "app" / "api" / "upload.py").read_text(encoding="utf-8")
    assert "amount_col = 'actual_commission' if 'actual_commission' in bc.columns" in source
    assert "rename(columns={amount_col:'actual_commission'})" in source
    assert "BC_AMOUNT_INVALID" in source

def test_dfs_reconciliation_panel_is_on_dashboard_not_data_upload():
    source = (ROOT.parent / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    dashboard = source[source.index("function ReconciliationView("):source.index("function DfsReconciliationPanel(")]
    upload = source[source.index("function UploadWorkspace("):source.index("function UploadCard(")]
    assert "<DfsReconciliationPanel historicalData={viewingHistory ? dfsCommission : null} viewingHistory={viewingHistory} />" in dashboard
    assert "function DfsReconciliationPanel({historicalData=null,viewingHistory=false})" in source
    assert "DFS Priorities Incentive — monthly reconciliation" in source
    assert "{dfsRecon?.available&&" not in upload
    assert "dfs-incentive/reconciliation" not in upload
