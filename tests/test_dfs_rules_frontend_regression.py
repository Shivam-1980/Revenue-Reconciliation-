from pathlib import Path


def test_dfs_panel_declares_and_loads_permanent_rules_before_rendering():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    start = source.index("function DfsReconciliationPanel(")
    end = source.index("function WomenCspIncentivePanel(", start)
    panel = source[start:end]
    assert "const [rules,setRules]=useState(null)" in panel
    assert "/api/upload/dfs-incentive/rules" in panel
    assert "setRules(d.rule_matrix || null)" in panel
    assert "{rules &&" not in panel
    assert "rulesError" in panel and "rulesLoading" in panel
