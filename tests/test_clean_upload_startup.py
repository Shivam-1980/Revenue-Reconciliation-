from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))

def test_clean_upload_startup_has_no_active_month_data():
    data=ROOT/'backend'/'app'/'data'
    meta=json.loads((data/'upload_metadata.json').read_text())
    for key in ('transactions','commission','csp_geography','rural_csp','social_security_counts','passbook_printing_counts','active_batch_id'):
        assert meta.get(key) is None
    assert meta['rate_master']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert meta['expected_commission_rule']['filename'] == 'SBI_Expected_Commission_Rule.xlsx'
    assert (data/'rate_master'/'latest_rate_master.csv').exists()
    assert (data/'expected_commission_rule'/'latest.xlsx').exists()
    assert not (data/'transactions'/'latest_transactions.csv').exists()
    assert not (data/'commissions'/'latest_commission.csv').exists()
    assert not (data/'supplemental'/'latest_social_security_counts.csv').exists()
    assert not (data/'supplemental'/'latest_passbook_printing_counts.csv').exists()
    # Historical CSP roster/source data must not ship in the clean-start package.
    assert not (data/'supplemental'/'latest_social_security_csp_master.csv').exists()
    assert not (ROOT/'docs'/'reference'/'legacy_august'/'latest_social_security_csp_master.csv').exists()


def test_release_does_not_bundle_historical_monthly_source_workbooks_or_outputs():
    assert not (ROOT / 'docs' / 'validation').exists()
    assert not (ROOT / 'docs' / 'august_2026_audit_inputs').exists()
    assert not (ROOT / 'docs' / 'validation' / 'august_2026_uploaded_sources').exists()
    assert not (ROOT / 'backend' / 'app' / 'data' / 'csp_id_aliases.csv').exists()
    assert not (ROOT / 'backend' / 'app' / 'data' / 'supplemental' / 'latest_social_security_csp_master.csv').exists()
