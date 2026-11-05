import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_startup_reset_version_is_bumped_and_month_agnostic():
    source = (ROOT / 'backend' / 'reset_initial_data.py').read_text(encoding='utf-8')
    assert "VERSION = '62.6.164-clean-state-every-start'" in source
    assert 'latest_transactions.csv' in source
    assert 'latest_commission.csv' in source
    assert 'latest_dfs_incentive_counts.csv' in source
    assert 'latest_women_csp_roster.csv' in source
    assert 'preloaded' not in source.lower()

def test_dfs_runtime_upload_is_cleared_on_clean_upgrade():
    source = (ROOT / 'backend' / 'reset_initial_data.py').read_text(encoding='utf-8')
    assert "'dfs_incentive': None" in source

def test_release_has_no_active_month_sources_registered():
    meta = json.loads((ROOT / 'backend' / 'app' / 'data' / 'upload_metadata.json').read_text(encoding='utf-8'))
    for key in ('transactions', 'commission', 'csp_geography', 'rural_csp',
                'social_security_counts', 'passbook_printing_counts', 'dfs_incentive', 'women_csp_roster'):
        assert meta.get(key) is None, key
    assert meta['rate_master']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert meta['expected_commission_rule']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert meta['active_batch_id'] is None
    assert (ROOT / 'backend' / 'app' / 'data' / 'rate_master' / 'latest_rate_master.csv').exists()
    assert (ROOT / 'backend' / 'app' / 'data' / 'expected_commission_rule' / 'latest.xlsx').exists()
