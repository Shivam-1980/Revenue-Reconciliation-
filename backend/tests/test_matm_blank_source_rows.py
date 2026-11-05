import pandas as pd
from app.api.upload import _drop_blank_matm_source_rows


def test_matm_upload_ignores_fully_blank_trailing_rows():
    raw = pd.DataFrame({
        'csp_id': ['1A859007', None, ''],
        'csp_name': ['Example CSP', None, '  '],
        'matm_transaction_count_august_2026': [8, None, ''],
        'matm_status': ['Yes', None, None],
    })
    cleaned = _drop_blank_matm_source_rows(
        raw, 'csp_id', 'csp_name', [('matm_transaction_count_august_2026', '2026-08')]
    )
    assert len(cleaned) == 1
    assert cleaned.iloc[0]['csp_id'] == '1A859007'


def test_matm_upload_does_not_silently_drop_partially_populated_rows():
    raw = pd.DataFrame({
        'csp_id': ['1A859007', None],
        'csp_name': ['Example CSP', 'Missing ID'],
        'matm_transaction_count_august_2026': [8, 3],
    })
    cleaned = _drop_blank_matm_source_rows(
        raw, 'csp_id', 'csp_name', [('matm_transaction_count_august_2026', '2026-08')]
    )
    assert len(cleaned) == 2


def test_matm_upload_ignores_string_null_tokens_in_blank_rows():
    raw = pd.DataFrame({
        'csp_id': ['1A859007', 'nan', 'None', ''],
        'csp_name': ['Example CSP', 'nan', 'null', '  '],
        'matm_transaction_count_august_2026': [8, float('nan'), float('nan'), ''],
    })
    cleaned = _drop_blank_matm_source_rows(
        raw, 'csp_id', 'csp_name', [('matm_transaction_count_august_2026', '2026-08')]
    )
    assert len(cleaned) == 1
    assert cleaned.iloc[0]['csp_id'] == '1A859007'


def test_matm_upload_retains_count_only_row_for_validation():
    raw = pd.DataFrame({
        'csp_id': [''],
        'csp_name': [''],
        'matm_transaction_count_august_2026': [3],
    })
    cleaned = _drop_blank_matm_source_rows(
        raw, 'csp_id', 'csp_name', [('matm_transaction_count_august_2026', '2026-08')]
    )
    assert len(cleaned) == 1
