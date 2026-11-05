import pandas as pd
from app.api.dashboard import _initial_deposit_conditional_summary_from_transactions


def test_initial_deposit_slab_boundaries_and_conditional_totals():
    tx = pd.DataFrame({
        'transaction_type': ['Initial Deposit'] * 8 + ['MONEY TRANSFER'],
        'amount': [0, 99.99, 100, 499.99, 500, 999.99, 1000, 27500, 200],
        'csp_id': ['C1','C1','C1','C2','C2','C2','C3','C4','C1'],
        'status': ['SUCCESS'] * 9,
        'transaction_id': [f'R{i}' for i in range(9)],
        'transaction_date': pd.to_datetime(['2026-08-01'] * 9),
    })
    result = _initial_deposit_conditional_summary_from_transactions(tx)
    assert result['status'] == 'CONDITIONAL_KYC_EVIDENCE_REQUIRED'
    assert result['successful_transactions'] == 8
    assert [x['transactions'] for x in result['slabs']] == [2, 2, 2, 2]
    assert result['conditional_ekyc_total'] == 280.00
    assert result['conditional_ovd_total'] == 70.00
    assert result['verified_expected_commission'] is None


def test_initial_deposit_missing_kyc_does_not_become_verified_commission():
    tx = pd.DataFrame({
        'transaction_type': ['INITIAL DEPOSIT'], 'amount': [1000], 'csp_id': ['C1']
    })
    result = _initial_deposit_conditional_summary_from_transactions(tx)
    assert result['conditional_ekyc_total'] == 50.00
    assert result['conditional_ovd_total'] == 10.00
    assert result['verified_expected_commission'] is None


def test_initial_deposit_csp_level_counts_and_conditional_commission():
    tx = pd.DataFrame({
        'transaction_type': ['INITIAL DEPOSIT'] * 5,
        'amount': [50, 100, 499, 500, 1000],
        'csp_id': ['C1', 'C1', 'C1', 'C2', 'C2'],
        'status': ['SUCCESS'] * 5,
    })
    result = _initial_deposit_conditional_summary_from_transactions(tx)
    assert result['successful_transactions'] == 5
    assert result['unique_csps'] == 2
    by_csp = {row['csp_id']: row for row in result['csp_summary']}
    assert by_csp['C1']['successful_transactions'] == 3
    assert by_csp['C1']['below_100_count'] == 1
    assert by_csp['C1']['100_to_499_count'] == 2
    assert by_csp['C1']['conditional_ekyc_commission'] == 80.0
    assert by_csp['C1']['conditional_ovd_commission'] == 25.0
    assert by_csp['C2']['500_to_999_count'] == 1
    assert by_csp['C2']['1000_plus_count'] == 1
    assert by_csp['C2']['conditional_ekyc_commission'] == 90.0
    assert by_csp['C2']['conditional_ovd_commission'] == 20.0
    assert all(row['condition_status'] == 'CONDITIONAL_KYC_EVIDENCE_REQUIRED' for row in result['csp_summary'])
