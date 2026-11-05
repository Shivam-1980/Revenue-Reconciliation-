import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'app' / 'data'


def test_distribution_starts_without_any_month_specific_active_sources():
    meta = json.loads((DATA / 'upload_metadata.json').read_text(encoding='utf-8'))
    for key in ('transactions', 'commission', 'csp_geography', 'rural_csp',
                'social_security_counts', 'passbook_printing_counts', 'dfs_incentive', 'women_csp_roster', 'tab_incentive'):
        assert meta[key] is None, key
    assert meta['rate_master']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert meta['rate_master']['validation']['valid'] is True
    assert meta['expected_commission_rule']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert meta['active_batch_id'] is None
    for path in (
        DATA / 'transactions' / 'latest_transactions.csv',
        DATA / 'commissions' / 'latest_commission.csv',
        DATA / 'rural_csp' / 'latest_rural_csp_master.csv',
        DATA / 'supplemental' / 'latest_social_security_counts.csv',
        DATA / 'supplemental' / 'latest_passbook_printing_counts.csv',
        DATA / 'supplemental' / 'latest_women_csp_roster.csv',
    ):
        assert not path.exists(), str(path)


def test_reference_mappings_remain_available_without_preloading_period_data():
    assert (DATA / 'rate_master' / 'latest_rate_master.csv').exists()
    assert (DATA / 'expected_commission_rule' / 'latest.xlsx').exists()
    assert (DATA / 'transaction_type_mapping_master.csv').exists()
    assert (DATA / 'rural_csp' / 'rural_transaction_type_mapping.csv').exists()
