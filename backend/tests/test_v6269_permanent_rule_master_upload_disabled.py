from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_authoritative_sbi_workbook_is_bundled_in_both_locations():
    import pandas as pd
    source = ROOT / "app" / "data" / "expected_commission_rule" / "latest.xlsx"
    approved = ROOT.parent / "docs" / "approved_master" / "SBI_Expected_Commission_Rule.xlsx"
    assert source.exists() and approved.exists()
    for sheet in ["Consolidated Commission Master", "Slabs & Incentive Matrices"]:
        a = pd.read_excel(source, sheet_name=sheet, header=None).fillna("")
        b = pd.read_excel(approved, sheet_name=sheet, header=None).fillna("")
        assert a.equals(b)


def test_upload_ui_does_not_require_monthly_rule_master():
    ui = (ROOT.parent / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    assert 'title="3. SBI Expected Commission Rule (Permanent Master)"' not in ui
    assert "bundled permanently with the project" in ui
    assert "Permanent SBI rules: Bundled and active" in ui


def test_rule_master_upload_route_is_locked_to_versioned_release():
    source = (ROOT / "app" / "api" / "upload.py").read_text(encoding="utf-8")
    route = source.split("@router.post('/rate-master')", 1)[1].split("@router.post('/expected-commission-rule')", 1)[0]
    assert "bundled permanently" in route.lower()
    assert "raise HTTPException(" in route
