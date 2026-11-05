import pandas as pd
from app.services.reconciliation_engine import resolve_transaction_types_series, mapping_confidence_series, build_reference_type_map


def test_series_resolver_preserves_fixed_mapping_and_variable_product_logic():
    types = pd.Series(['MONEY TRANSFER', 'MONEY TRANSFER', 'INITIAL DEPOSIT', 'CUSTOMER ENROLL FOR SSS'])
    amounts = pd.Series([100.0, 500.0, 750.0, 20.0])
    dates = pd.to_datetime(pd.Series(['2026-08-01', '2026-08-02', '2026-08-03', '2026-08-04']))
    refs = build_reference_type_map(pd.DataFrame({'transaction_type': ['MONEY TRANSFER', 'PMSBY', 'ACCOUNT OPPENING (PMJDY)']}))
    result = resolve_transaction_types_series(types, amounts, dates, refs)
    assert result.iloc[0] == 'FUNDTRANSFER - NON HOME'
    assert result.iloc[1] == 'FUNDTRANSFER - NON HOME'
    assert result.iloc[2] == 'ACCOUNT OPPENING (PMJDY)'
    assert result.iloc[3] == 'PMSBY'


def test_confidence_lookup_returns_one_value_per_source_row():
    types = pd.Series(['MONEY TRANSFER'] * 1000 + ['UNKNOWN TYPE'] * 10)
    result = mapping_confidence_series(types)
    assert len(result) == len(types)
    assert result.iloc[0] == result.iloc[999]
    assert result.iloc[-1] == 'UNMAPPED'
