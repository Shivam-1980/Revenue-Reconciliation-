from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_maps_network_fetch_failure_to_actionable_backend_diagnostic():
    source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    assert "const friendlyApiError = (error, action = \"request\")" in source
    assert "Cannot connect to the Revenue Reconciliation backend" in source
    assert "http://127.0.0.1:8000/health" in source
    assert "friendlyApiError(e, \"run reconciliation\")" in source
    assert "friendlyApiError(e, `upload ${file.name}`)" in source


def test_launcher_waits_for_both_services_before_opening_dashboard():
    source = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8000/health" in source
    assert "http://127.0.0.1:5173/" in source
    assert ":FAILED" in source
