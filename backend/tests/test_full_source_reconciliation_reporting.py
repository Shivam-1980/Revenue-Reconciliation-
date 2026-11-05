from pathlib import Path


def test_social_security_endpoint_exposes_full_source_control_separately():
    src = Path(__file__).parents[1] / "app" / "api" / "reconciliation.py"
    text = src.read_text(encoding="utf-8")
    assert "full_source_control" in text
    assert "unresolved_source_commission_indicative_not_approved" in text
    assert "full_source_expected_commission_indicative" in text


def test_dashboard_labels_valid_and_indicative_totals_separately():
    src = Path(__file__).parents[2] / "frontend" / "src" / "main.jsx"
    text = src.read_text(encoding="utf-8")
    assert "Expected commission (valid CSPs)" in text
    assert "Full-source expected (indicative)" in text
    assert "Unresolved indicative commission" in text
