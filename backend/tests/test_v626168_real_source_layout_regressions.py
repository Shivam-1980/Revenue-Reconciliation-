from io import BytesIO
import pandas as pd

from app.api.upload import _month_from_text, _clean_supplement_columns


def test_filename_month_is_explicit_for_generic_matm_transaction_header():
    filename = "mATM transaction Sep 26.xlsx"
    raw = _clean_supplement_columns(pd.DataFrame(columns=["CSP Code", "CSP Name", "mATM Transaction"]))
    assert _month_from_text(filename) == "2026-09"
    assert {"csp_code", "csp_name", "matm_transaction"}.issubset(set(raw.columns))


def test_tab_source_uses_tab_transactions_header_and_month_filename():
    filename = "TAB Transaction Sep 26.xlsx"
    raw = _clean_supplement_columns(pd.DataFrame(columns=["CSP code", "CSP name", "TAB transactions", "Incentive (Rs)", "Monthly cap (Rs)"]))
    assert _month_from_text(filename) == "2026-09"
    assert "tab_transactions" in raw.columns
    assert "csp_code" in raw.columns


def test_rural_paid_amount_is_not_login_day_evidence():
    # The Rural Commission paid amount report cannot be accepted as an eligibility roster.
    from app.services.rural_commission import _find_sheet_and_header
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        pd.DataFrame([["CSP Code", "CSP Name", "Rural Commission (Rs)"], ["1A859005", "Sample", 2000]]).to_excel(writer, sheet_name="Rural Commission Sep 26", index=False, header=False)
    try:
        _find_sheet_and_header(stream.getvalue())
    except ValueError as exc:
        assert "paid-amount report" in str(exc)
        assert "Total Login Day" in str(exc)
    else:
        raise AssertionError("A paid amount must not be accepted as login-day eligibility evidence")
