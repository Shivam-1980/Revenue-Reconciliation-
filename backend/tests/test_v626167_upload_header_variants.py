from io import BytesIO
import pandas as pd

from app.api.upload import _month_from_text, _clean_supplement_columns
from app.services.rural_commission import parse_rural_csp_workbook, _period_from_login_header


def test_month_parser_handles_month_year_filename_and_normalized_header():
    assert _month_from_text('mATM transaction Sep 26.xlsx') == '2026-09'
    assert _month_from_text('m_atm_transaction_count_sep_26') == '2026-09'
    assert _month_from_text('TAB Transaction Sep 26.xlsx') == '2026-09'


def test_rural_login_header_normalized_underscores_maps_period():
    period, start, end, label = _period_from_login_header(['total_login_day_sep_26'])
    assert (period, start, end) == ('2026-09', '2026-09-01', '2026-09-30')


def test_rural_workbook_accepts_csp_code_and_month_labelled_login_day():
    frame = pd.DataFrame({
        'CSP Code': ['1A851234'],
        'CSP Name': ['Sample CSP'],
        "Total Login Day Sep-26": [22],
    })
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        pd.DataFrame([['Rural CSP Eligibility Report', None, None]]).to_excel(writer, sheet_name='Report', index=False, header=False)
        frame.to_excel(writer, sheet_name='Report', index=False, startrow=2)
    parsed, meta = parse_rural_csp_workbook(stream.getvalue(), 'Rural Commission Sep 26.xlsx')
    assert meta['period'] == '2026-09'
    assert parsed.iloc[0]['csp_id'] == '1A851234'
    assert parsed.iloc[0]['login_days'] == 22


def test_supplement_header_normalization_keeps_singular_tab_and_matm_labels():
    df = pd.DataFrame(columns=['CSP Code', 'TAB Transaction Sep 26', 'mATM Transaction Sep 26'])
    cleaned = _clean_supplement_columns(df)
    assert 'csp_code' in cleaned.columns
    assert 'tab_transaction_sep_26' in cleaned.columns
    assert 'matm_transaction_sep_26' in cleaned.columns
