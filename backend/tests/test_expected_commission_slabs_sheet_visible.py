from pathlib import Path
import pandas as pd
from app.api.source_data import _load_expected_rule_sheet

ROOT = Path(__file__).resolve().parents[1]
RULE_PATH = ROOT / "app" / "data" / "expected_commission_rule" / "latest.xlsx"

def test_bundled_rule_workbook_contains_slabs_and_incentive_matrix():
    xl = pd.ExcelFile(RULE_PATH, engine="openpyxl")
    assert xl.sheet_names == ["Consolidated Commission Master", "Slabs & Incentive Matrices"]
    matrix = pd.read_excel(RULE_PATH, sheet_name="Slabs & Incentive Matrices", header=None, engine="openpyxl").fillna("")
    flat = " ".join(str(x) for x in matrix.to_numpy().ravel()).lower()
    for expected in ["dfs", "monthly extra incentive", "1,200", "1,500", "1,800", "2,200", "5,000", "average balance multiplier"]:
        assert expected in flat

def test_source_data_reader_returns_second_sheet_rows():
    df, chosen, sheets, header_row = _load_expected_rule_sheet("Slabs & Incentive Matrices")
    assert chosen == "Slabs & Incentive Matrices"
    assert sheets == ["Consolidated Commission Master", "Slabs & Incentive Matrices"]
    assert len(df) == 19  # blank spacer rows are intentionally omitted by the source viewer
    assert header_row is None
    assert df.astype(str).apply(lambda col: col.str.contains("Monthly Extra Incentive", case=False, regex=False)).any().any()
