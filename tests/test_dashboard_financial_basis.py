import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.api.reconciliation import TX
import pytest


@pytest.mark.skipif(not TX.exists(), reason="Financial dashboard controls require uploaded source fixtures")
def test_dashboard_financial_control_uses_same_comparable_basis():
    client = TestClient(app)
    data = client.get("/api/dashboard/summary").json()
    expected = data.get("expected_commission_comparable")
    actual = data.get("actual_comparable_commission")
    variance = data.get("comparable_variance")
    assert expected is not None and actual is not None and variance is not None
    assert abs((float(expected) - float(actual)) - float(variance)) < 0.01


@pytest.mark.skipif(not TX.exists(), reason="Financial dashboard controls require uploaded source fixtures")
def test_dashboard_exposes_transaction_amount_and_penalty_controls():
    client = TestClient(app)
    data = client.get("/api/dashboard/summary").json()
    assert float(data["transaction_amount"]) > 0
    assert float(data["penalty_amount"]) >= 0
    assert data["bc_workbook_internal_control_status"] == "PASS"


def test_api_version_matches_v62_package():
    client = TestClient(app)
    data = client.get("/api/version").json()
    assert data.get("version") == "62.6.164-clean-state-every-start"



def test_dashboard_headline_and_health_donut_use_same_uploaded_control_scope():
    """Headline includes uploaded supplemental controls; Rule 24 stays separate."""
    frontend = Path(__file__).resolve().parents[1] / "frontend" / "src" / "main.jsx"
    source = frontend.read_text(encoding="utf-8")
    assert "const heroRate = heroControlGroups > 0 ? (heroMatchedGroups / heroControlGroups) * 100 : 0;" in source
    assert "const displayedHealthRate = displayedHeroRate;" in source
    assert "const healthMatchedGroups = allSourceRateAvailable ? heroMatchedGroups" in source
    assert "social_security_matched_controls" in source
    assert "passbook_printing_matched_controls" in source
    assert "deliberately kept as a separate monthly incentive KPI" in source
    assert "management_control_rate_including_dfs_and_women_csp" not in source


def test_headline_and_health_percentage_rounding_is_identical_for_screenshot_counts():
    matched, total = 3887, 5921
    expected = round(matched / total * 100, 1)
    assert expected == 65.6
    frontend = Path(__file__).resolve().parents[1] / "frontend" / "src" / "main.jsx"
    source = frontend.read_text(encoding="utf-8")
    assert "const displayedHealthRate = displayedHeroRate;" in source


def test_api_health_and_release_version_smoke():
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json().get("status") == "healthy"
    version = client.get("/api/version")
    assert version.status_code == 200
    assert version.json().get("version") == "62.6.164-clean-state-every-start"
