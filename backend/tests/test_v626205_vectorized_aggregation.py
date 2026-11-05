"""Vectorized group aggregation must keep the lambda-era financial semantics.

Most important: a group whose values are all blank stays blank (not Rs 0), so a
missing expected/actual commission is never silently reported as zero.
"""
import numpy as np
import pandas as pd

from app.services.reconciliation_engine import _group_aggregate, aggregate_by_csp_and_type


def test_sum_min1_keeps_all_blank_group_blank_and_zero_as_zero():
    df = pd.DataFrame({
        'csp_id': ['A', 'A', 'B', 'B', 'C'],
        'amount': [10.0, np.nan, np.nan, np.nan, 0.0],
        'label': ['x', 'y', None, 'z', 'w'],
    })
    out = _group_aggregate(df, ['csp_id'], [
        ('total', 'amount', 'sum_min1'), ('plain', 'amount', 'sum'),
        ('rows', 'amount', 'size'), ('first_label', 'label', 'first'),
    ]).set_index('csp_id')
    assert out.loc['A', 'total'] == 10.0
    assert pd.isna(out.loc['B', 'total'])
    assert out.loc['C', 'total'] == 0.0
    assert out.loc['B', 'plain'] == 0.0
    assert out.loc['B', 'rows'] == 2
    assert out.loc['B', 'first_label'] == 'z'  # first non-null, as named-agg 'first'


def test_group_aggregate_matches_lambda_reference_on_random_data():
    rng = np.random.default_rng(5)
    n = 2000
    df = pd.DataFrame({
        'csp_id': rng.choice(['A', 'B', 'C', None], n),
        'transaction_type': rng.choice(['T1', 'T2', 'T3'], n),
        'v': np.where(rng.random(n) < 0.3, np.nan, rng.normal(100, 30, n).round(2)),
    })
    fast = _group_aggregate(df, ['csp_id', 'transaction_type'], [('v', 'v', 'sum_min1')])
    ref = df.groupby(['csp_id', 'transaction_type'], dropna=False).agg(
        v=('v', lambda x: x.sum(min_count=1))).reset_index()
    pd.testing.assert_frame_equal(fast, ref, check_dtype=False, atol=1e-9)


def test_aggregate_by_csp_and_type_coerces_text_amounts_and_keeps_blanks():
    r = pd.DataFrame({
        'csp_id': ['A', 'A', 'B'], 'transaction_type': ['T', 'T', 'T'],
        'successful_transactions': [1, 2, 1], 'transaction_amount': [100.0, 200.0, 50.0],
        'expected_commission': [1.0, 2.0, np.nan], 'verified_expected_commission': [1.0, np.nan, np.nan],
        'actual_comparable_commission': ['1.5', 'bad', None], 'actual_commission': [1.5, 1.0, None],
        'financial_gap': [0.5, None, None], 'report_base': [1, 2, None], 'count_variance': [0, 1, None],
        'reconciliation_status': ['MATCH', 'MATCH', 'MISSING'], 'financial_gap_status': ['OK', 'OK', 'NA'],
        'exception_flag': [False, True, True], 'investigation_status': ['x', 'y', 'z'],
        'mismatch_reason': ['', 'r', 'm'],
    })
    out = aggregate_by_csp_and_type(r).set_index('csp_id')
    assert out.loc['A', 'successful_transactions'] == 3
    assert out.loc['A', 'expected_commission'] == 3.0
    assert out.loc['A', 'actual_commission'] == 1.5          # 'bad' coerced to blank, not an error
    assert out.loc['A', 'exception_flag']
    assert pd.isna(out.loc['B', 'expected_commission'])
    assert pd.isna(out.loc['B', 'actual_commission'])
    assert pd.isna(out.loc['B', 'variance'])
