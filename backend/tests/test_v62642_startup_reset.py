import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_startup_reset_clears_month_specific_sources_on_release_upgrade():
    source = (ROOT / 'reset_initial_data.py').read_text(encoding='utf-8')
    assert "VERSION = '62.6.216-ui-security-speed'" in source
    assert 'Upload fresh current-period sources to reconcile.' in source
    assert 'latest_transactions.csv' in source
    assert 'latest_commission.csv' in source
    assert 'latest_dfs_incentive_counts.csv' in source
    assert 'latest_women_csp_roster.csv' in source
    assert 'latest_tab_incentive_counts.csv' in source
    assert "'tab_incentive': None" in source
    assert "'loan_lead_generation': None" in source
    assert 'latest_loan_lead_generation.csv' in source
    assert "'dfs_incentive': None" in source
    assert "'women_csp_roster': None" in source
    assert 'latest_women_csp_roster.csv' in source
    assert 'latest_tab_incentive_counts.csv' in source
    assert "'tab_incentive': None" in source
    assert "'loan_lead_generation': None" in source
    assert 'latest_loan_lead_generation.csv' in source
    assert 'preloaded' not in source.lower()


def test_release_has_empty_period_metadata():
    meta = json.loads((ROOT / 'app' / 'data' / 'upload_metadata.json').read_text(encoding='utf-8'))
    for key in ('transactions', 'commission', 'csp_geography', 'rural_csp',
                'social_security_counts', 'passbook_printing_counts', 'dfs_incentive', 'women_csp_roster', 'tab_incentive', 'loan_lead_generation'):
        assert meta.get(key) is None, key
    assert meta['rate_master']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert meta['expected_commission_rule']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert meta['active_batch_id'] is None
    assert (ROOT / 'app' / 'data' / 'rate_master' / 'latest_rate_master.csv').exists()
    assert (ROOT / 'app' / 'data' / 'expected_commission_rule' / 'latest.xlsx').exists()



def test_reset_clears_active_data_every_start_but_preserves_permanent_rules():
    source = (ROOT / 'reset_initial_data.py').read_text(encoding='utf-8')
    assert "if MARKER.exists()" not in source
    assert "latest_transactions.csv" in source
    assert "latest_commission.csv" in source
    assert "latest_matm_incentive_counts.csv" in source
    assert "latest_social_security_counts.csv" in source
    assert "latest_women_csp_roster.csv" in source
    assert "latest_rate_master.csv" in source  # normalized runtime copy is rebuilt
    assert "expected_commission_rule" in source
    assert "latest.xlsx" in source  # permanent approved workbook is preserved
