import json
from app.services import upload_metadata as um


def seed(meta_path, tx_batch='old', cm_batch='old', active='old'):
    data={
        'transactions': {'filename':'old-tx.xlsx','batch_id':tx_batch,'sha256':'oldtx'},
        'commission': {'filename':'old-bc.xlsx','batch_id':cm_batch,'sha256':'oldbc'},
        'rate_master': {'filename':'approved-rates.xlsx','batch_id':active,'sha256':'rates','validation':{'valid':True}},
        'csp_geography': None, 'rural_csp': {'filename':'old-rural.xlsx','batch_id':active},
        'social_security_counts': None, 'passbook_printing_counts': None,
        'active_batch_id':active,
    }
    meta_path.write_text(json.dumps(data))


def test_replacing_both_month_sources_joins_same_new_batch(tmp_path, monkeypatch):
    meta_path=tmp_path/'upload_metadata.json'
    monkeypatch.setattr(um, 'META', meta_path)
    seed(meta_path)
    um.prepare_source_upload('transactions','newtx')
    um.save_source('transactions','new-tx.xlsx','Sheet1',10,'2026-09-01','2026-09-30',sha256='newtx')
    first=um.load_metadata()['active_batch_id']
    um.prepare_source_upload('commission','newbc')
    um.save_source('commission','new-bc.xlsx','Sheet1',20,'2026-09-01','2026-09-30',sha256='newbc')
    data=um.load_metadata()
    assert data['transactions']['batch_id']==first
    assert data['commission']['batch_id']==first
    assert data['rate_master']['batch_id']==first
    assert data['rural_csp']['batch_id']=='old'  # evidence remains period-bound; engine filters it


def test_upload_order_can_start_with_commission(tmp_path, monkeypatch):
    meta_path=tmp_path/'upload_metadata.json'
    monkeypatch.setattr(um, 'META', meta_path)
    seed(meta_path)
    um.prepare_source_upload('commission','newbc')
    um.save_source('commission','new-bc.xlsx','Sheet1',20,'2026-09-01','2026-09-30',sha256='newbc')
    first=um.load_metadata()['active_batch_id']
    um.prepare_source_upload('transactions','newtx')
    um.save_source('transactions','new-tx.xlsx','Sheet1',10,'2026-09-01','2026-09-30',sha256='newtx')
    data=um.load_metadata()
    assert data['transactions']['batch_id']==first
    assert data['commission']['batch_id']==first
    assert data['rate_master']['batch_id']==first


def test_replacing_source_in_current_complete_batch_starts_new_batch(tmp_path, monkeypatch):
    meta_path=tmp_path/'upload_metadata.json'
    monkeypatch.setattr(um, 'META', meta_path)
    seed(meta_path, tx_batch='current', cm_batch='current', active='current')
    um.prepare_source_upload('transactions','replacement')
    assert um.load_metadata()['active_batch_id'] != 'current'


def test_failed_upload_attempt_is_visible_and_successful_save_clears_it(tmp_path, monkeypatch):
    meta_path = tmp_path / 'upload_metadata.json'
    monkeypatch.setattr(um, 'META', meta_path)
    seed(meta_path)
    um.record_upload_failure('transactions', 'replacement.xlsx', 'Missing transaction date')
    data = um.load_metadata()
    assert data['upload_attempt_errors']['transactions']['filename'] == 'replacement.xlsx'
    assert data['transactions']['filename'] == 'old-tx.xlsx'  # last known good source is preserved
    um.prepare_source_upload('transactions', 'goodtx')
    um.save_source('transactions', 'replacement.xlsx', 'Sheet1', 10, '2026-09-01', '2026-09-30',
                   extra={'validation': {'valid': True}}, sha256='goodtx')
    assert 'transactions' not in um.load_metadata()['upload_attempt_errors']
