from app.api import reconciliation as api


def _meta(tx_start='2026-09-01', tx_end='2026-09-30', cm_start='2026-09-15', cm_end='2026-10-15', invalid_success_rows=0):
    return {
        'transactions': {
            'filename': 'success_sep.xlsx', 'batch_id': 'batch-1',
            'period_start': tx_start, 'period_end': tx_end,
            'validation': {'valid': True, 'invalid_success_rows': invalid_success_rows,
                           'duplicate_successful_transaction_ids': 0,
                           'negative_success_amount_rows': 0},
        },
        'commission': {
            'filename': 'bc_sep.xlsx', 'batch_id': 'batch-1',
            'period_start': cm_start, 'period_end': cm_end,
            'validation': {'valid': True, 'invalid_commission_values': 0},
        },
        'rate_master': {'filename': 'approved.xlsx', 'validation': {'valid': True, 'errors': []}},
        # Geography and Rural CSP are optional for the core reconciliation run.
        'csp_geography': None,
        'rural_csp': None,
    }


def _patch_paths(monkeypatch, tmp_path, meta):
    for name in ('TX', 'CM', 'RM', 'GEO', 'RURAL'):
        p = tmp_path / name
        if name in ('TX', 'CM', 'RM'):
            p.write_text('stub')
        monkeypatch.setattr(api, name, p)
    monkeypatch.setattr(api, 'load_metadata', lambda: meta)
    monkeypatch.setattr(api, '_signature', lambda: {'test': True})
    monkeypatch.setattr(api, 'read_cached', lambda signature: None)


def test_status_blocks_partial_period_coverage_even_when_periods_overlap(monkeypatch, tmp_path):
    meta = _meta()  # dates overlap, but BC starts later and ends after tx period
    _patch_paths(monkeypatch, tmp_path, meta)
    result = api.reconciliation_status()
    assert result['period_overlap'] is True
    assert result['period_coverage_ok'] is False
    assert result['ready_to_run'] is False
    assert any('Incomplete commission-period coverage' in x for x in result['readiness_errors'])


def test_status_validates_required_sources_when_optional_rural_or_geography_missing(monkeypatch, tmp_path):
    meta = _meta(tx_start='2026-09-01', tx_end='2026-09-30', cm_start='2026-09-01', cm_end='2026-09-30', invalid_success_rows=3)
    _patch_paths(monkeypatch, tmp_path, meta)
    result = api.reconciliation_status()
    assert result['sources']['rural_csp'] is False
    assert result['sources']['csp_geography'] is False
    assert result['ready_to_run'] is False
    assert any('3 successful transaction row(s) have invalid mandatory financial fields' in x for x in result['readiness_errors'])


def test_status_allows_core_run_when_required_sources_are_valid_and_periods_match(monkeypatch, tmp_path):
    meta = _meta(tx_start='2026-09-01', tx_end='2026-09-30', cm_start='2026-09-01', cm_end='2026-09-30')
    _patch_paths(monkeypatch, tmp_path, meta)
    result = api.reconciliation_status()
    assert result['ready_to_run'] is True
    assert result['readiness_errors'] == []
    assert result['period_coverage_ok'] is True


def test_failed_latest_upload_attempt_blocks_reconciliation_until_success(monkeypatch, tmp_path):
    meta = _meta(tx_start='2026-09-01', tx_end='2026-09-30', cm_start='2026-09-01', cm_end='2026-09-30')
    meta['upload_attempt_errors'] = {
        'transactions': {'filename': 'replacement_bad.xlsx', 'message': 'Missing transaction date'}
    }
    _patch_paths(monkeypatch, tmp_path, meta)
    result = api.reconciliation_status()
    assert result['sources']['transactions'] is False
    assert result['ready_to_run'] is False
    assert any('previous source is preserved but reconciliation is blocked' in x for x in result['readiness_errors'])
