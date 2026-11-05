from io import BytesIO
import pandas as pd
from fastapi.testclient import TestClient
import pytest


def _xlsx(sheets):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine='openpyxl') as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return bio.getvalue()


@pytest.mark.parametrize("identity_sheet", ["Payment Status", "CSP Identity Master"])
def test_women_roster_resolves_noncanonical_id_from_current_period_bc_crosswalk(tmp_path, monkeypatch, identity_sheet):
    from app.main import app
    from app.api import upload

    # Isolate all file state so the test proves that identity resolution is based
    # only on the current BC workbook, not a persisted CSP alias or August fixture.
    for name in ('TX', 'CM', 'RM', 'GEO', 'RURAL', 'SUPPLEMENTAL'):
        path = tmp_path / name.lower()
        path.mkdir()
        monkeypatch.setattr(upload, name, path)
    monkeypatch.setattr(upload, 'WOMEN_COUNTS', tmp_path / 'supplemental' / 'latest_women_csp_roster.csv')
    monkeypatch.setattr(upload, 'WOMEN_META', tmp_path / 'supplemental' / 'latest_women_csp_roster_metadata.json')
    monkeypatch.setattr(upload, 'CSP_IDENTITY', tmp_path / 'supplemental' / 'latest_csp_identity_crosswalk.csv')
    monkeypatch.setattr(upload, 'CSP_IDENTITY_META', tmp_path / 'supplemental' / 'latest_csp_identity_crosswalk_metadata.json')

    metadata = {'active_batch_id': None, 'commission': None, 'transactions': None}

    def fake_prepare(kind, sha256=None):
        if not metadata['active_batch_id']:
            metadata['active_batch_id'] = 'batch-aug-2026'
        return metadata

    def fake_save(kind, filename, sheet_name, rows, period_start=None, period_end=None, extra=None, sha256=None):
        metadata[kind] = {'filename': filename, 'sheet_name': sheet_name, 'rows': rows,
                          'period_start': period_start, 'period_end': period_end,
                          'batch_id': metadata['active_batch_id'], 'sha256': sha256}
        if extra:
            metadata[kind].update(extra)
        return metadata

    monkeypatch.setattr(upload, 'prepare_source_upload', fake_prepare)
    monkeypatch.setattr(upload, 'save_source', fake_save)
    monkeypatch.setattr(upload, 'load_metadata', lambda: metadata)
    monkeypatch.setattr(upload, 'clear_cache', lambda: None)

    bc_bytes = _xlsx({
        identity_sheet: pd.DataFrame({
            'CSP_CODE': ['1A859006', '1A859006', '1A850111'],
            'CSP_NAME': ['SAMPLE  AGENT', 'SAMPLE  AGENT', 'OTHER CSP'],
            'POPULATION': ['RURAL', 'RURAL', 'URBAN'],
        }),
        'CSP Wise Transaction Type Wise': pd.DataFrame({
            'CSP_CODE': ['1A859006'], 'TRANSACTION_TYPE': ['IMPS FUND TRANSFER'], 'COMMISSION': [12.5]
        }),
    })
    roster_bytes = _xlsx({
        'CSP Summary Aug': pd.DataFrame({
            'CSP ID': ['OTHER ISSUE'], 'CSP Name': ['Sample Agent'],
            'Total Transaction Count Aug\'26': [100], 'Terminal Status': ['Active'], 'Population': ['Rural']
        })
    })

    client = TestClient(app)
    bc = client.post('/api/upload/commission', files={'file': ('BC Report AUG-26.xlsx', bc_bytes,
                     'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert bc.status_code == 200, bc.text

    # A supplemental upload may advance the global active batch marker while the
    # current BC workbook remains unchanged. Identity must remain bound to the BC
    # workbook's own batch + SHA, not fail solely because that global marker changed.
    metadata['active_batch_id'] = 'later-supplement-batch'
    roster = client.post('/api/upload/women-csp-roster', files={'file': ('Women_CSP_Aug.xlsx', roster_bytes,
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert roster.status_code == 200, roster.text
    result = roster.json()['validation']
    assert result['valid'] is True
    assert result['approved_alias_mappings'] == {'OTHER ISSUE | Sample Agent': '1A859006'}
    assert result['alias_mapped_rows'] == 1
    saved = pd.read_csv(upload.WOMEN_COUNTS, dtype=str)
    assert saved.loc[0, 'csp_id'] == '1A859006'
