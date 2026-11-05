from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UPLOADED_MASTER = ROOT / "docs" / "approved_master" / "SBI_Expected_Commission_Rule.xlsx"
RUNTIME_MASTER = ROOT / "backend" / "app" / "data" / "expected_commission_rule" / "latest.xlsx"

def _sheet_values(path, sheet):
    return pd.read_excel(path, sheet_name=sheet, header=None).fillna("").astype(str)

def test_uploaded_sbi_master_and_runtime_master_are_identical():
    for sheet in ["Consolidated Commission Master", "Slabs & Incentive Matrices"]:
        assert _sheet_values(UPLOADED_MASTER, sheet).equals(_sheet_values(RUNTIME_MASTER, sheet))

def test_all_consolidated_rule_rows_have_conditions_rates_and_cycle():
    df = pd.read_excel(UPLOADED_MASTER, sheet_name="Consolidated Commission Master", header=3)
    df = df.dropna(how="all")
    df = df[df["Category / Service"].notna()]
    required = [
        "Category / Service", "Component / Particulars",
        "Slab / Condition / Details", "Rural / Semi-Urban (INR)",
        "Urban / Metro (INR)", "Type & Cycle"
    ]
    assert len(df) == 71
    assert not df[required].isna().any().any()
    assert df["Component / Particulars"].astype(str).str.strip().ne("").all()

def test_incentive_matrix_sheet_has_rows_and_dfs_cap_evidence():
    df = pd.read_excel(UPLOADED_MASTER, sheet_name="Slabs & Incentive Matrices", header=None).fillna("")
    text = " ".join(df.astype(str).values.ravel()).upper()
    assert "DEPARTMENT OF FINANCIAL SERVICES" in text
    assert "AVERAGE BALANCE" in text
