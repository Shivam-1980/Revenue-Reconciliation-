import pandas as pd
from app.api.upload import _passbook_count_column, _month_from_text, _normalized_supplement_df


def test_passbook_count_column_does_not_select_printer_status():
    columns = [
        "csp_id", "csp_name", "population", "passbook_printer_status",
        "passbook_printing_count_sep_26",
    ]
    assert _passbook_count_column(columns) == "passbook_printing_count_sep_26"


def test_passbook_status_alone_is_not_a_count_column():
    assert _passbook_count_column(["csp_id", "passbook_printer_status"]) is None


def test_uploaded_september_2026_workbook_header_and_rows():
    from pathlib import Path
    source = Path("/mnt/data/Passbook Printing Sep 26.xlsx")
    if not source.exists():
        return
    raw, sheet = _normalized_supplement_df(source.read_bytes(), source.name)
    count_col = _passbook_count_column(raw.columns)
    assert sheet == "Passbook Printer Yes - Sep 26"
    assert "csp_id" in raw.columns
    assert count_col == "passbook_printing_count_sep_26"
    assert _month_from_text(source.name) == "2026-09"
    assert pd.to_numeric(raw[count_col], errors="coerce").gt(0).sum() == 94
