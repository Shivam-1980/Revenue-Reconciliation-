import asyncio
import json
from io import BytesIO
from pathlib import Path

from starlette.datastructures import UploadFile
from app.api import upload as upload_api
from app.services import upload_metadata as um


def test_invalid_transaction_upload_records_blocker_without_overwriting_last_good_source(monkeypatch, tmp_path):
    data = tmp_path / 'data'
    tx = data / 'transactions'; cm = data / 'commissions'; rm = data / 'rate_master'
    geo = data / 'csp_geography'; rural = data / 'rural_csp'; supp = data / 'supplemental'
    for folder in (tx, cm, rm, geo, rural, supp):
        folder.mkdir(parents=True, exist_ok=True)
    (tx / 'latest_transactions.csv').write_text('transaction_id,csp_id,transaction_type,amount,transaction_date\nOLD,1A851234,Money Transfer,100,2026-09-01\n')
    meta_path = data / 'upload_metadata.json'
    meta_path.write_text(json.dumps({
        'transactions': {'filename':'old_good.csv','sha256':'oldhash','batch_id':'batch1','validation':{'valid':True}},
        'commission': {'filename':'old_bc.csv','sha256':'bchash','batch_id':'batch1','validation':{'valid':True}},
        'rate_master': {'filename':'approved.xlsx','batch_id':None,'validation':{'valid':True}},
        'csp_geography':None,'rural_csp':None,'active_batch_id':'batch1'
    }))
    monkeypatch.setattr(um, 'META', meta_path)
    for attr, value in {
        'TX':tx, 'CM':cm, 'RM':rm, 'GEO':geo, 'RURAL':rural, 'SUPPLEMENTAL':supp,
        'SOCIAL_COUNTS':supp/'latest_social_security_counts.csv',
        'SOCIAL_EXCEPTIONS_PATH':supp/'latest_social_security_counts_exceptions.csv',
        'PASSBOOK_COUNTS':supp/'latest_passbook_printing_counts.csv',
        'PASSBOOK_EXCEPTIONS':supp/'latest_passbook_printing_count_exceptions.csv',
        'DFS_COUNTS':supp/'latest_dfs_incentive_counts.csv', 'DFS_META':supp/'latest_dfs_incentive_metadata.json',
        'WOMEN_COUNTS':supp/'latest_women_csp_roster.csv', 'WOMEN_META':supp/'latest_women_csp_roster_metadata.json',
        'CSP_IDENTITY':supp/'latest_csp_identity_crosswalk.csv', 'CSP_IDENTITY_META':supp/'latest_csp_identity_crosswalk_metadata.json',
    }.items():
        monkeypatch.setattr(upload_api, attr, value)

    bad_csv = b'not_a_transaction_header\nhello\n'
    result = asyncio.run(upload_api.transactions(UploadFile(filename='replacement_bad.csv', file=BytesIO(bad_csv))))
    saved_meta = um.load_metadata()
    assert result['saved'] is False
    assert saved_meta['transactions']['filename'] == 'old_good.csv'
    assert saved_meta['upload_attempt_errors']['transactions']['filename'] == 'replacement_bad.csv'
    assert 'Missing required columns' in saved_meta['upload_attempt_errors']['transactions']['message']
