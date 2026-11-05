from pathlib import Path

from app.api import reconciliation


def test_signature_changes_when_women_csp_roster_changes(tmp_path, monkeypatch):
    data = reconciliation.BASE_DIR / 'data'
    target = data / 'supplemental' / 'latest_women_csp_roster.csv'
    original = target.read_bytes() if target.exists() else None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('csp_id,transaction_count\n1A850001,10\n', encoding='utf-8')
        first = reconciliation._signature()
        target.write_text('csp_id,transaction_count\n1A850001,11\n', encoding='utf-8')
        second = reconciliation._signature()
        assert first['women_csp_roster'] != second['women_csp_roster']
    finally:
        if original is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(original)


def test_signature_includes_rule_mappings_and_month_metadata():
    signature = reconciliation._signature()
    for key in (
        'transaction_type_mapping_master', 'rural_transaction_type_mapping',
        'approved_rule_master_reference', 'metadata_transactions',
        'metadata_commission', 'metadata_rate_master', 'metadata_women_csp_roster',
        'dfs_incentive_counts', 'tab_incentive_counts', 'loan_lead_generation',
    ):
        assert key in signature


def test_signature_tracks_active_transaction_file_bytes_even_with_stale_metadata():
    target = reconciliation.TX
    original = target.read_bytes() if target.exists() else None
    meta_path = reconciliation.BASE_DIR / 'data' / 'upload_metadata.json'
    meta_original = meta_path.read_bytes() if meta_path.exists() else None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('csp_id,transaction_type,successful_transactions\n1A850001,MONEY TRANSFER,1\n', encoding='utf-8')
        first = reconciliation._signature()
        target.write_text('csp_id,transaction_type,successful_transactions\n1A850001,MONEY TRANSFER,2\n', encoding='utf-8')
        second = reconciliation._signature()
        assert first['transactions'] != second['transactions']
    finally:
        if original is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(original)
        if meta_original is not None:
            meta_path.write_bytes(meta_original)
