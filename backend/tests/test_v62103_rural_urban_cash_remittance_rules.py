from pathlib import Path
import pandas as pd
from app.services.rate_master import calculate_expected, _canonical_commercial_type, build_rate_master_from_workbook
from app.services.reconciliation_engine import resolve_transaction_type

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'data' / 'rate_master'


def _rules():
    return pd.read_csv(ROOT / 'latest_rate_master.csv', low_memory=False)


def _calc(label, amount, channel):
    tx = pd.DataFrame([{
        'rule_type': label, 'csp_id': 'CSP001', 'amount': amount,
        'channel': channel, 'transaction_date': '2026-08-15', 'kyc_type': ''
    }])
    out, _ = calculate_expected(tx, _rules())
    return out.iloc[0]


def test_rural_urban_cash_withdrawal_percentage_floor_cap_and_fixed_slabs():
    assert _calc('CASH WITHDRAWAL', 100, 'RURAL').expected_commission == 3.00
    assert _calc('CASH WITHDRAWAL', 10000, 'RURAL').expected_commission == 15.00
    assert _calc('CASH WITHDRAWAL', 10000, 'URBAN').expected_commission == 17.00
    assert _calc('CASH WITHDRAWAL', 12000, 'RURAL').expected_commission == 17.00
    assert _calc('CASH WITHDRAWAL', 18000, 'URBAN').expected_commission == 22.00
    assert _calc('CASH WITHDRAWAL', 25000, 'RURAL').expected_commission == 23.00


def test_rural_urban_cash_deposit_and_minimum_amount_gate():
    assert _calc('CASH DEPOSIT', 100, 'RURAL').expected_commission == 2.00
    assert _calc('CASH DEPOSIT', 10000, 'URBAN').expected_commission == 10.00
    assert _calc('CASH DEPOSIT', 12000, 'URBAN').expected_commission == 12.00
    assert pd.isna(_calc('CASH DEPOSIT', 99, 'RURAL').expected_commission)
    assert pd.isna(_calc('CASH WITHDRAWAL', 99, 'URBAN').expected_commission)


def test_remittance_cash_and_transfer_are_not_collapsed_to_generic_money_transfer():
    cash = 'REMITTANCE (CASH) (TRANSACTION AMOUNT RS.100 & ABOVE) (NON-HOME BRANCH A/CS) (NO RECOVERY FROM CUSTOMERS)'
    transfer = 'REMITTANCE (TRANSFER) (HOME BRANCH A/CS) (NO RECOVERY FROM CUSTOMERS)'
    assert _canonical_commercial_type(cash) == 'FUNDTRANSFER - NON HOME'
    assert _canonical_commercial_type(transfer) == 'FUNDTRANSFER - HOME'
    assert resolve_transaction_type(cash) == 'FUNDTRANSFER - NON HOME'
    assert resolve_transaction_type(transfer) == 'FUNDTRANSFER - HOME'
    assert _calc(cash, 5000, 'RURAL').expected_commission == 8.00
    assert _calc(cash, 5000, 'URBAN').expected_commission == 10.00
    assert _calc(transfer, 5000, 'RURAL').expected_commission == 10.00
    assert _calc(transfer, 5000, 'URBAN').expected_commission == 12.00
    assert _calc(cash, 12000, 'RURAL').expected_commission == 10.00
    assert _calc(transfer, 12000, 'URBAN').expected_commission == 15.00


def test_geography_is_required_not_guessed():
    row = _calc('CASH WITHDRAWAL', 1000, '')
    assert pd.isna(row.expected_commission)
    assert row.rate_status in {'Rate Master Missing', 'Ambiguous Rate Rule', 'Geography Required'}


def test_uploaded_sbi_workbook_parser_preserves_100_rupee_minimum_for_all_four_products():
    workbook = ROOT.parent / 'expected_commission_rule' / 'latest.xlsx'
    rules, validation = build_rate_master_from_workbook(workbook.read_bytes(), 'SBI_Expected_Commission_Rule.xlsx')
    assert validation['valid'] is True
    for typ in ['CASH WITHDRAWAL', 'CASH DEPOSIT', 'FUNDTRANSFER - NON HOME', 'FUNDTRANSFER - HOME']:
        slab = rules[
            rules['transaction_type'].eq(typ)
            & rules['rate_type'].astype(str).str.upper().eq('PERCENTAGE')
            & pd.to_numeric(rules['max_amount'], errors='coerce').between(9999.99, 10000.01)
        ]
        assert len(slab) >= 2, typ
        assert set(pd.to_numeric(slab['min_amount'], errors='coerce').dropna().tolist()) == {100.0}, typ
