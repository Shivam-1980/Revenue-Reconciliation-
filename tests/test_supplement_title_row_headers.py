from io import BytesIO
from pathlib import Path
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.api.upload import _read_supplement_sheet_with_header, _clean_supplement_columns, _normalized_supplement_df, _month_from_text


def _workbook(rows, sheet):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name=sheet, header=False, index=False)
    return buf.getvalue()


def test_detects_title_rows_before_passbook_csp_header():
    content = _workbook([
        ["PASSBOOK PRINTING - SEPTEMBER 2026 (CSP-wise)", None, None],
        ["Source: SBI report", None, None],
        [None, None, None],
        ["CSP code", "CSP name", "Passbook prints Sep"],
        ["1A850123", "Example CSP", 12],
    ], "1 Passbook Printing")
    df = _read_supplement_sheet_with_header(content, "1 Passbook Printing")
    df = _clean_supplement_columns(df)
    assert "csp_code" in df.columns
    assert "passbook_prints_sep" in df.columns
    assert str(df.iloc[0]["csp_code"]) == "1A850123"


def test_detects_title_rows_before_pmjjby_pmsby_wide_counts():
    content = _workbook([
        ["PMJJBY AND PMSBY - SEPTEMBER 2026 (CSP-wise)", None, None],
        ["Source: SBI report", None, None],
        [None, None, None],
        ["CSP code", "PMJJBY done", "PMSBY done"],
        ["1A850123", 4, 7],
    ], "2 PMJJBY-PMSBY")
    df = _clean_supplement_columns(_read_supplement_sheet_with_header(content, "2 PMJJBY-PMSBY"))
    assert "csp_code" in df.columns
    assert "pmjjby_done" in df.columns
    assert "pmsby_done" in df.columns
    assert _month_from_text("PMJJBY-PMSBY_Sep 26.xlsx") == "2026-09"


def test_passbook_header_aliases_accept_csp_code_and_csp_code_new():
    from app.api.upload import _alias_columns
    for header in ["CSP code", "CSP Code New", "CSP ID"]:
        df = pd.DataFrame({header: ["1A850123"], "Passbook prints Sep": [12]})
        df.columns = df.columns.astype(str).str.strip().str.lower().str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_")
        out, mapped = _alias_columns(df, {"csp_id":["csp_id","csp_code","csp_code_new","csp","csp_id_code","csp_code_id"]})
        assert "csp_id" in out.columns, (header, list(df.columns))


def test_passbook_month_named_count_header_is_recognized():
    from app.api.upload import _month_from_text
    header = "passbook_prints_sep"
    assert "passbook" in header and "print" in header
    assert _month_from_text("Passbook Printing Sep 2026.xlsx") == "2026-09"
