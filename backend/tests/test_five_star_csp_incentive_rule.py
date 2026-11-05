from pathlib import Path
import pandas as pd
from app.services.five_star_incentive import calculate_five_star_incentive, MONTHLY_RATE_INR

ROOT = Path(__file__).resolve().parents[1]


def test_five_star_all_five_criteria_gives_500_monthly():
    result = calculate_five_star_incentive({
        "a_rating": "Yes", "passbook_printer": True, "micro_atm": "Yes",
        "uv_lamp": "Yes", "voice_prompt": "Yes",
    })
    assert result["status"] == "ELIGIBLE"
    assert result["expected_commission"] == 500
    assert result["frequency"] == "Monthly"


def test_five_star_any_failed_criterion_is_not_eligible():
    result = calculate_five_star_incentive({
        "a_rating": "Yes", "passbook_printer": True, "micro_atm": "Yes",
        "uv_lamp": "No", "voice_prompt": "Yes",
    })
    assert result["status"] == "NOT_ELIGIBLE"
    assert result["expected_commission"] == 0


def test_five_star_missing_evidence_does_not_guess_expected_amount():
    result = calculate_five_star_incentive({
        "a_rating": "Yes", "passbook_printer": True, "micro_atm": "Yes",
        "uv_lamp": "", "voice_prompt": "Yes",
    })
    assert result["status"] == "EVIDENCE_REQUIRED"
    assert result["expected_commission"] is None
    assert result["missing_criteria"] == ["uv_lamp"]


def test_dfs_matrix_in_uploaded_permanent_workbook_matches_screenshot():
    path = ROOT / "app" / "data" / "expected_commission_rule" / "latest.xlsx"
    df = pd.read_excel(path, sheet_name="Slabs & Incentive Matrices", header=None)
    # Find the matrix by scheme labels rather than relying on a fixed row number.
    rows = df.fillna("").astype(str).values.tolist()
    text = "\\n".join(" | ".join(row) for row in rows)
    assert "PMJDY (Account Opening)" in text
    assert "PMJJBY (Life Insurance)" in text
    assert "PMSBY (Accident Insurance)" in text
    assert "APY (Atal Pension Yojana)" in text
    assert "Rs. 2,200/-" in text and "Rs. 5,000/-" in text
    assert "0.85%" in text and "1.00%" in text


def test_uploaded_master_contains_five_star_500_monthly_all_criteria():
    df = pd.read_excel(ROOT / "app" / "data" / "expected_commission_rule" / "latest.xlsx",
                       sheet_name="Consolidated Commission Master", header=3).fillna("")
    rows = df[df["Component / Particulars"].astype(str).str.upper().str.contains("5 STAR CSP INCENTIVE")]
    assert len(rows) == 1
    row = rows.iloc[0]
    assert "500" in str(row["Rural / Semi-Urban (INR)"])
    assert "500" in str(row["Urban / Metro (INR)"])
    assert "A-Rating" in str(row["Slab / Condition / Details"])
    assert "Monthly" in str(row["Type & Cycle"])
