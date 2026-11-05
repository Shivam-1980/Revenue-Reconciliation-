from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_refresh_clear_endpoint_is_registered_and_versioned():
    source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.post("/api/workspace/clear-current-data")' in source
    assert ('62.6.179-safety-baseline' in source or '62.6.181-startup-launch-fix' in source or '62.6.184-platform-foundation-plus' in source)
    assert 'namespace["main"]()' in source

def test_frontend_clears_backend_on_full_page_load():
    source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    assert '/api/workspace/clear-current-data' in source
    assert 'method:"POST"' in source
    assert 'Uploaded period files and generated results are cleared server-side' in source

def test_reset_preserves_permanent_rulebook_and_clears_period_data():
    source = (ROOT / "backend" / "reset_initial_data.py").read_text(encoding="utf-8")
    assert "expected_commission_rule' / 'latest.xlsx'" in source
    assert "latest_transactions.csv" in source
    assert "latest_commission.csv" in source
    assert "latest_matm_incentive_metadata.json" in source
