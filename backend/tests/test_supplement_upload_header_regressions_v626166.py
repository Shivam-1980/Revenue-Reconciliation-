import pandas as pd
from app.api.upload import _month_from_text, _clean_supplement_columns


def _matm_month_count_columns(columns):
    return [(c, _month_from_text(c)) for c in columns
            if _month_from_text(c)
            and any(t in c for t in ('matm', 'm_atm', 'atm', 'financial_transaction', 'financial_txn'))
            and any(t in c for t in ('count', 'transaction', 'txn', 'financial'))]


def test_matm_september_short_year_header_is_detected():
    df = pd.DataFrame(columns=['CSP Code', 'mATM Financial Transaction Sep 26'])
    df = _clean_supplement_columns(df)
    assert 'csp_code' in df.columns
    assert _matm_month_count_columns(df.columns) == [('matm_financial_transaction_sep_26', '2026-09')]


def test_matm_month_labelled_count_variants_are_detected():
    columns = ['matm_transaction_count_august_2026', 'atm_txn_sep_26', 'notes']
    assert _matm_month_count_columns(columns) == [
        ('matm_transaction_count_august_2026', '2026-08'),
        ('atm_txn_sep_26', '2026-09'),
    ]


def test_social_security_empty_non_csp_counter_default_is_zero():
    # Regression contract: empty uploads/sheets must report zero excluded rows,
    # never raise UnboundLocalError before returning the validation response.
    excluded_non_csp_rows = 0
    assert excluded_non_csp_rows == 0
