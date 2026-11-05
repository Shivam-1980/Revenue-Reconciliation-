import json
import shutil
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.api import upload as upload_api
from app.api import reconciliation as reconciliation_api
from app.services import upload_metadata as upload_metadata_service
from app.services import reconciliation_cache as cache_service


def test_month_label_uploads_can_reach_reconciliation_run(monkeypatch, tmp_path):
    data = tmp_path / 'data'
    tx_dir = data / 'transactions'; cm_dir = data / 'commissions'; rm_dir = data / 'rate_master'
    geo_dir = data / 'csp_geography'; rural_dir = data / 'rural_csp'; supp_dir = data / 'supplemental'; audit_dir = data / 'audit'
    for folder in (tx_dir, cm_dir, rm_dir, geo_dir, rural_dir, supp_dir, audit_dir):
        folder.mkdir(parents=True, exist_ok=True)
    source_root = Path(__file__).resolve().parents[1] / 'app' / 'data'
    shutil.copy2(source_root / 'rate_master' / 'latest_rate_master.csv', rm_dir / 'latest_rate_master.csv')
    shutil.copy2(source_root / 'rate_master' / 'approved_rule_master_reference.csv', rm_dir / 'approved_rule_master_reference.csv')
    meta_source = json.loads((source_root / 'upload_metadata.json').read_text(encoding='utf-8'))
    meta_source.update({
        'transactions': None, 'commission': None, 'csp_geography': None, 'rural_csp': None,
        'social_security_counts': None, 'passbook_printing_counts': None, 'dfs_incentive': None,
        'women_csp_roster': None, 'tab_incentive': None, 'loan_lead_generation': None,
        'upload_attempt_errors': {}, 'active_batch_id': None,
    })
    meta_path = data / 'upload_metadata.json'
    meta_path.write_text(json.dumps(meta_source, indent=2), encoding='utf-8')
    monkeypatch.setattr(upload_metadata_service, 'META', meta_path)

    # Point upload routes to isolated test storage.
    for name, value in {
        'TX': tx_dir, 'CM': cm_dir, 'RM': rm_dir, 'GEO': geo_dir, 'RURAL': rural_dir,
        'SUPPLEMENTAL': supp_dir,
        'SOCIAL_COUNTS': supp_dir / 'latest_social_security_counts.csv',
        'SOCIAL_EXCEPTIONS_PATH': supp_dir / 'latest_social_security_counts_exceptions.csv',
        'PASSBOOK_COUNTS': supp_dir / 'latest_passbook_printing_counts.csv',
        'PASSBOOK_EXCEPTIONS': supp_dir / 'latest_passbook_printing_count_exceptions.csv',
        'DFS_COUNTS': supp_dir / 'latest_dfs_incentive_counts.csv', 'DFS_META': supp_dir / 'latest_dfs_incentive_metadata.json',
        'WOMEN_COUNTS': supp_dir / 'latest_women_csp_roster.csv', 'WOMEN_META': supp_dir / 'latest_women_csp_roster_metadata.json',
        'CSP_IDENTITY': supp_dir / 'latest_csp_identity_crosswalk.csv', 'CSP_IDENTITY_META': supp_dir / 'latest_csp_identity_crosswalk_metadata.json',
    }.items():
        monkeypatch.setattr(upload_api, name, value)
    monkeypatch.setattr(upload_api, 'clear_cache', lambda: None)
    monkeypatch.setattr(upload_api, 'save_snapshot', lambda *args, **kwargs: None)
    monkeypatch.setattr(upload_api, '_refresh_processing_snapshot', lambda: None)

    # Point reconciliation routes and their audit artifacts to isolated storage.
    for name, value in {
        'TX': tx_dir / 'latest_transactions.csv', 'CM': cm_dir / 'latest_commission.csv',
        'RM': rm_dir / 'latest_rate_master.csv', 'GEO': geo_dir / 'latest_csp_geography.csv',
        'AUDIT': audit_dir / 'latest_condition_audit.csv', 'AUDIT_SUMMARY': audit_dir / 'latest_condition_summary.json',
    }.items():
        monkeypatch.setattr(reconciliation_api, name, value)
    monkeypatch.setattr(reconciliation_api, 'read_cached', lambda signature: None)
    monkeypatch.setattr(reconciliation_api, 'get_or_compute', lambda signature, fn: (fn(), False))
    monkeypatch.setattr(reconciliation_api, 'create_run_record', lambda *args, **kwargs: {
        'run_id': 'synthetic-run', 'exception_groups': 0, 'expected_commission': 0.0,
        'actual_commission': 0.0, 'variance': 0.0,
    })

    tx_csv = (
        'Reference Number,CSP Code,Type of Transaction,Amount,Date,Status\n'
        'SYN-001,1A851234,AEPS ONUS WITHDRAWAL,1000,2026-09-15,SUCCESS\n'
    ).encode()
    cm_csv = (
        'CSP Code,Transaction Type,Commission,Month\n'
        '1A851234,AEPS ONUS WITHDRAWAL,20,Sep 2026\n'
    ).encode()
    client = TestClient(app)
    tx_resp = client.post('/api/upload/transactions', files={'file': ('success_sep.csv', BytesIO(tx_csv), 'text/csv')})
    assert tx_resp.status_code == 200, tx_resp.text
    assert tx_resp.json()['saved'] is True, tx_resp.text
    cm_resp = client.post('/api/upload/commission', files={'file': ('bc_sep.csv', BytesIO(cm_csv), 'text/csv')})
    assert cm_resp.status_code == 200, cm_resp.text
    assert cm_resp.json()['saved'] is True, cm_resp.text

    status = client.get('/api/reconciliation/status')
    assert status.status_code == 200, status.text
    status_json = status.json()
    assert status_json['ready_to_run'] is True, status_json
    assert status_json['upload_sources']['commission']['period_start'] == '2026-09-01'
    assert status_json['upload_sources']['commission']['period_end'] == '2026-09-30'

    run_resp = client.post('/api/reconciliation/run')
    assert run_resp.status_code == 200, run_resp.text
    assert run_resp.json()['message'] == 'Reconciliation completed'
    csp_resp = client.get('/api/reconciliation/csp')
    assert csp_resp.status_code == 200, csp_resp.text
    assert isinstance(csp_resp.json(), list)
    assert len(csp_resp.json()) >= 1, 'Synthetic successful transaction did not produce any CSP reconciliation control.'
    assert any(str(row.get('csp_id', '')).strip() == '1A851234' for row in csp_resp.json()), csp_resp.json()
