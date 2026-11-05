import pandas as pd
from app.services.reconciliation_engine import resolve_transaction_type, build_reference_type_map
from app.services.rate_master import build_rate_master_from_workbook, calculate_expected
from pathlib import Path


def test_money_transfer_maps_to_sbi_rule_6a_non_home_and_fund_transfer_to_6b_home():
    # V62.6.216: the bank pays Money Transfer on the Remittance (Cash) non-home schedule (SBI item 6.a): on Sep/Aug 2026 data
    # 95-97% of agents with equal counts match to the rupee. Home-branch Remittance (Transfer, 6.b) is the FUND TRANSFER label.
    refs = build_reference_type_map(pd.DataFrame({'transaction_type': ['MONEY TRANSFER', 'FUNDTRANSFER - HOME', 'FUNDTRANSFER - NON HOME']}))
    assert resolve_transaction_type('Money Transfer', 5000, refs) == 'FUNDTRANSFER - NON HOME'
    assert resolve_transaction_type('Fund Transfer', 5000, refs) == 'FUNDTRANSFER - HOME'
    assert resolve_transaction_type('FUNDTRANSFER - HOME', 5000, refs) == 'FUNDTRANSFER - HOME'


def test_rule_6b_expected_commission_for_rural_and_urban_slabs():
    rule_path = Path(__file__).resolve().parents[1] / 'app' / 'data' / 'expected_commission_rule' / 'latest.xlsx'
    rules, meta = build_rate_master_from_workbook(rule_path.read_bytes(), rule_path.name)
    assert meta['valid']
    rows = []
    for amount in [100, 10000, 10001, 15000, 15001, 20000, 20001, 30000]:
        for channel in ['RURAL', 'URBAN']:
            rows.append({'rule_type': 'FUNDTRANSFER - HOME', 'amount': amount, 'channel': channel, 'csp_id': '1A850001'})
    result, _ = calculate_expected(pd.DataFrame(rows), rules)
    assert result['expected_commission'].notna().all(), result[['amount', 'channel', 'rate_status']].to_string()
    got = {(int(r.amount), r.channel): round(float(r.expected_commission), 2) for r in result.itertuples()}
    assert got[(100, 'RURAL')] == 3.0
    assert got[(100, 'URBAN')] == 3.0
    assert got[(10000, 'RURAL')] == 10.0
    assert got[(10000, 'URBAN')] == 12.0
    assert got[(10001, 'RURAL')] == 12.0
    assert got[(10001, 'URBAN')] == 15.0
    assert got[(15001, 'RURAL')] == 15.0
    assert got[(15001, 'URBAN')] == 17.0
    assert got[(20001, 'RURAL')] == 18.0
    assert got[(20001, 'URBAN')] == 20.0
