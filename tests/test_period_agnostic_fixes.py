import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.api.upload import _month_from_text, _month_bounds
from app.services.reconciliation_engine import reconcile_transactions


def test_month_parser_supports_arbitrary_month_labels_without_august_hardcoding():
    assert _month_from_text('Sep 2026') == '2026-09'
    assert _month_from_text('passbook_prints_October-2027.xlsx') == '2027-10'
    assert _month_from_text('2028-02') == '2028-02'
    assert _month_bounds('2028-02') == ('2028-02-01', '2028-02-29')
    assert _month_from_text('monthly_file.xlsx') is None


def test_passbook_geography_comes_from_current_bc_source_not_supplement():
    tx = pd.DataFrame([{
        'transaction_id': 'TX-1', 'csp_id': '1A850001',
        'transaction_type': 'Money Transfer', 'amount': 100,
        'transaction_date': '2026-09-12', 'status': 'SUCCESS'
    }])
    commission = pd.DataFrame([{
        'csp_id': '1A850001', 'transaction_type': 'PASSBOOK PRINTING',
        'report_base': 1, 'actual_commission': 5, 'channel': 'RURAL'
    }])
    rules = pd.DataFrame([
        {'rule_id': 'PB-RURAL', 'transaction_type': 'PASSBOOK PRINTING', 'channel': 'RURAL', 'rate': 5.0, 'rule_status': 'CONFIRMED'},
        {'rule_id': 'PB-URBAN', 'transaction_type': 'PASSBOOK PRINTING', 'channel': 'URBAN', 'rate': 6.0, 'rule_status': 'CONFIRMED'},
    ])
    # Deliberately wrong supplemental geography/rate. These are not authoritative.
    supplement = pd.DataFrame([{
        'csp_id': '1A850001', 'transaction_type': 'PASSBOOK PRINTING',
        'count': 1, 'population': 'URBAN', 'rate': 6.0, 'period': 'Sep-2026'
    }])
    result = reconcile_transactions(tx, commission, rules, passbook_printing_counts=supplement)
    pb = result[result['transaction_type'].eq('PASSBOOK PRINTING')]
    assert len(pb) == 1
    assert float(pb.iloc[0]['expected_commission']) == 5.0


def test_passbook_source_loader_accepts_missing_population_and_rate(tmp_path, monkeypatch):
    import app.services.reconciliation_engine as engine
    path = tmp_path / 'counts.csv'
    pd.DataFrame([{
        'csp_id': '1A850001', 'transaction_type': 'PASSBOOK PRINTING',
        'count': 10, 'period': '2026-09'
    }]).to_csv(path, index=False)
    monkeypatch.setattr(engine, 'PASSBOOK_COUNTS_PATH', path)
    out = engine.load_passbook_printing_counts()
    assert len(out) == 1
    assert out.iloc[0]['count'] == 10
    assert pd.isna(out.iloc[0]['rate'])


def test_passbook_upload_accepts_month_named_column_and_uses_period_from_header(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from io import BytesIO
    import app.api.upload as upload
    from app.main import app

    target = tmp_path / 'passbook_counts.csv'
    monkeypatch.setattr(upload, 'PASSBOOK_COUNTS', target)
    monkeypatch.setattr(upload, 'save_source', lambda *a, **k: {})
    monkeypatch.setattr(upload, 'clear_cache', lambda: None)
    body = b'CSP Code,CSP Name,Sep 2026\n1A850001,Example CSP,42\n'
    response = TestClient(app).post('/api/upload/passbook-printing-counts', files={'file': ('passbook.csv', body, 'text/csv')})
    assert response.status_code == 200, response.text
    saved = pd.read_csv(target)
    assert saved.iloc[0]['period'] == '2026-09'
    assert saved.iloc[0]['count'] == 42
    assert saved.iloc[0]['transaction_type'] == 'PASSBOOK PRINTING'


def test_social_security_upload_requires_period_and_preserves_premium_evidence(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.upload as upload
    from app.main import app

    target = tmp_path / 'social_counts.csv'
    monkeypatch.setattr(upload, 'SOCIAL_COUNTS', target)
    monkeypatch.setattr(upload, 'save_source', lambda *a, **k: {})
    monkeypatch.setattr(upload, 'clear_cache', lambda: None)
    body = (b'CSP Code,Transaction Type,Count,Premium,Period\n'
            b'1A850001,PMJJBY,2,436,Sep-2026\n')
    response = TestClient(app).post('/api/upload/social-security-counts', files={'file': ('ss.csv', body, 'text/csv')})
    assert response.status_code == 200, response.text
    saved = pd.read_csv(target)
    assert saved.iloc[0]['period'] == '2026-09'
    assert saved.iloc[0]['premium'] == 436
    # Count-only official scheme source is accepted without inventing premium.
    # Validation must explicitly report the missing premium evidence.
    count_only = b'CSP Code,Transaction Type,Count,Period\n1A850001,PMJJBY,2,Sep-2026\n'
    response = TestClient(app).post('/api/upload/social-security-counts', files={'file': ('ss.csv', count_only, 'text/csv')})
    assert response.status_code == 200, response.text
    assert response.json()['validation']['premium_evidence'] == 'NOT_PROVIDED_IN_SOURCE'
    saved = pd.read_csv(target)
    assert pd.isna(saved.iloc[0]['premium'])


def test_rural_control_blocks_ambiguous_multi_month_input(tmp_path, monkeypatch):
    import app.api.reconciliation as reconciliation
    tx_path = tmp_path / 'transactions.csv'
    pd.DataFrame([
        {'transaction_id': 'A', 'csp_id': '1A850001', 'transaction_type': 'Money Transfer', 'amount': 10, 'transaction_date': '2026-09-01', 'status': 'SUCCESS'},
        {'transaction_id': 'B', 'csp_id': '1A850001', 'transaction_type': 'Money Transfer', 'amount': 10, 'transaction_date': '2026-10-01', 'status': 'SUCCESS'},
    ]).to_csv(tx_path, index=False)
    monkeypatch.setattr(reconciliation, 'TX', tx_path)
    result = reconciliation.rural_commission()
    assert result['available'] is False
    assert result['status'] == 'MULTI_PERIOD_UNSUPPORTED'
    assert result['summary']['transaction_periods'] == ['2026-09', '2026-10']


def test_august_passbook_control_is_not_reused_for_september():
    from app.services.reconciliation_engine import load_passbook_printing_reconciliation
    assert load_passbook_printing_reconciliation('2026-09').empty
    # Clean-upload release has no August workbook bundled; no period is active before upload.
    assert load_passbook_printing_reconciliation('2026-08').empty


def test_supplement_period_validation_supports_multiple_uploaded_months_without_stale_periods():
    from app.services.reconciliation_engine import (
        social_security_supplement_active, passbook_supplement_active,
    )
    months = ['2026-08', '2026-09']
    ss = pd.DataFrame([
        {'csp_id':'1A850001','transaction_type':'PMJJBY','count':2,'premium':436,'period':'2026-08'},
        {'csp_id':'1A850001','transaction_type':'PMJJBY','count':3,'premium':436,'period':'2026-09'},
    ])
    pb = pd.DataFrame([
        {'csp_id':'1A850001','transaction_type':'PASSBOOK PRINTING','count':2,'period':'2026-08'},
        {'csp_id':'1A850001','transaction_type':'PASSBOOK PRINTING','count':3,'period':'2026-09'},
    ])
    assert social_security_supplement_active(ss, transaction_months=months)
    assert passbook_supplement_active(pb, transaction_months=months)
    assert not passbook_supplement_active(pb.iloc[:1], transaction_months=months)
    stale = pd.concat([pb, pd.DataFrame([{
        'csp_id':'1A850001','transaction_type':'PASSBOOK PRINTING','count':7,'period':'2026-10'
    }])], ignore_index=True)
    assert not passbook_supplement_active(stale, transaction_months=months)


def test_multi_month_social_security_uses_each_period_rate_and_never_august_only_assumption():
    tx = pd.DataFrame([
        {'transaction_id':'TX-A','csp_id':'1A850001','transaction_type':'Money Transfer','amount':100,
         'transaction_date':'2026-08-10','status':'SUCCESS'},
        {'transaction_id':'TX-B','csp_id':'1A850001','transaction_type':'Money Transfer','amount':100,
         'transaction_date':'2026-09-10','status':'SUCCESS'},
    ])
    commission = pd.DataFrame([{
        'csp_id':'1A850001','transaction_type':'PMJJBY','report_base':5,'actual_commission':100,
        'channel':'RURAL'
    }])
    rules = pd.DataFrame([
        {'rule_id':'PMJJBY-TEST','transaction_type':'PMJJBY','channel':'ALL','rate':30.0,'rule_status':'CONFIRMED'},
    ])
    ss = pd.DataFrame([
        {'csp_id':'1A850001','transaction_type':'PMJJBY','count':2,'premium':436,'period':'2026-08'},
        {'csp_id':'1A850001','transaction_type':'PMJJBY','count':3,'premium':436,'period':'2026-09'},
    ])
    result = reconcile_transactions(tx, commission, rules, social_security_counts=ss)
    row = result[result['transaction_type'].eq('PMJJBY') & result['is_supplemental'].fillna(False)]
    assert len(row) == 1
    # August: 2 x ₹30; September: 3 x ₹22.50. The current rule is applied per row period.
    assert round(float(row.iloc[0]['expected_commission']), 2) == 127.50
    assert int(row.iloc[0]['successful_transactions']) == 5


def test_multi_month_passbook_aggregates_period_rates_before_joining_actual_commission():
    tx = pd.DataFrame([
        {'transaction_id':'TX-A','csp_id':'1A850001','transaction_type':'Money Transfer','amount':100,
         'transaction_date':'2026-08-10','status':'SUCCESS'},
        {'transaction_id':'TX-B','csp_id':'1A850001','transaction_type':'Money Transfer','amount':100,
         'transaction_date':'2026-09-10','status':'SUCCESS'},
    ])
    commission = pd.DataFrame([{
        'csp_id':'1A850001','transaction_type':'PASSBOOK PRINTING','report_base':5,
        'actual_commission':26,'channel':'RURAL'
    }])
    rules = pd.DataFrame([
        {'rule_id':'PB-RURAL','transaction_type':'PASSBOOK PRINTING','channel':'RURAL','rate':5.0,'rule_status':'CONFIRMED'},
        {'rule_id':'PB-URBAN','transaction_type':'PASSBOOK PRINTING','channel':'URBAN','rate':6.0,'rule_status':'CONFIRMED'},
    ])
    pb = pd.DataFrame([
        {'csp_id':'1A850001','transaction_type':'PASSBOOK PRINTING','count':2,'population':'URBAN','rate':6,'period':'2026-08'},
        {'csp_id':'1A850001','transaction_type':'PASSBOOK PRINTING','count':3,'population':'URBAN','rate':6,'period':'2026-09'},
    ])
    result = reconcile_transactions(tx, commission, rules, passbook_printing_counts=pb)
    row = result[result['transaction_type'].eq('PASSBOOK PRINTING')]
    assert len(row) == 1
    # BC geography is Rural and authoritative, so 5 prints x ₹5; actual is joined once.
    assert float(row.iloc[0]['expected_commission']) == 25.0
    assert float(row.iloc[0]['actual_commission']) == 26.0
    assert int(row.iloc[0]['successful_transactions']) == 5


def test_passbook_upload_expands_multiple_month_columns(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.upload as upload
    from app.main import app
    target = tmp_path / 'passbook_counts.csv'
    monkeypatch.setattr(upload, 'PASSBOOK_COUNTS', target)
    monkeypatch.setattr(upload, 'save_source', lambda *a, **k: {})
    monkeypatch.setattr(upload, 'clear_cache', lambda: None)
    body = b'CSP Code,CSP Name,Aug 2026,Sep 2026\n1A850001,Example CSP,10,12\n'
    response = TestClient(app).post('/api/upload/passbook-printing-counts', files={'file': ('passbook.csv', body, 'text/csv')})
    assert response.status_code == 200, response.text
    saved = pd.read_csv(target).sort_values('period')
    assert saved['period'].tolist() == ['2026-08', '2026-09']
    assert saved['count'].tolist() == [10, 12]


def test_social_security_upload_accepts_scheme_tabs_and_month_columns(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from io import BytesIO
    import app.api.upload as upload
    from app.main import app
    target = tmp_path / 'social_counts.csv'
    monkeypatch.setattr(upload, 'SOCIAL_COUNTS', target)
    monkeypatch.setattr(upload, 'save_source', lambda *a, **k: {})
    monkeypatch.setattr(upload, 'clear_cache', lambda: None)
    content = BytesIO()
    with pd.ExcelWriter(content, engine='openpyxl') as writer:
        pd.DataFrame({'CSP Code':['1A850001', ''], 'CSP Name':['Example', ''], 'August 2026':[2, None]}).to_excel(writer, sheet_name='PMJJBY', index=False)
        pd.DataFrame({'CSP Code':['1A850002', ''], 'CSP Name':['Example 2', ''], 'August 2026':[3, None]}).to_excel(writer, sheet_name='PMSBY', index=False)
    response = TestClient(app).post('/api/upload/social-security-counts', files={'file': ('PMJJBY_PMSBY_CSP_wise_August_2026.xlsx', content.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code == 200, response.text
    saved = pd.read_csv(target)
    assert set(saved['transaction_type']) == {'PMJJBY', 'PMSBY'}
    assert set(saved['period']) == {'2026-08'}
    assert saved['count'].sum() == 5


def test_passbook_upload_ignores_blank_footer_rows(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.upload as upload
    from app.main import app
    target = tmp_path / 'passbook_counts.csv'
    monkeypatch.setattr(upload, 'PASSBOOK_COUNTS', target)
    monkeypatch.setattr(upload, 'save_source', lambda *a, **k: {})
    monkeypatch.setattr(upload, 'clear_cache', lambda: None)
    body = b'CSP Code,CSP Name,August 2026\n1A850001,Example,42\n,,\n'
    response = TestClient(app).post('/api/upload/passbook-printing-counts', files={'file': ('Passbook_Printing_CSP_wise_August_2026.csv', body, 'text/csv')})
    assert response.status_code == 200, response.text
    saved = pd.read_csv(target)
    assert len(saved) == 1 and saved.iloc[0]['count'] == 42


def test_all_source_control_kpi_adds_uploaded_supplementals_but_keeps_women_separate():
    from app.services.control_kpi import all_source_control_kpi
    # August source audit: transaction + Rural = 2,960/4,821; PMJJBY/PMSBY =
    # 790/795; Passbook = 88/99. Women CSP Rule 24 is deliberately not passed in.
    assert all_source_control_kpi(
        transaction_matched=2627, transaction_groups=4463,
        rural_matched=333, rural_groups=358,
        social_security_matched=790, social_security_groups=795,
        passbook_matched=88, passbook_groups=99,
    ) == (3838, 5715, 67.16)


def test_all_source_control_kpi_includes_dfs_only_when_uploaded_and_ready():
    from app.services.control_kpi import all_source_control_kpi
    assert all_source_control_kpi(
        transaction_matched=2627, transaction_groups=4463,
        rural_matched=333, rural_groups=358,
        dfs_matched=65, dfs_groups=149,
    ) == (3025, 4970, 60.87)


def test_passbook_upload_preserves_populated_invalid_csp_as_exception_not_silent_drop(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.upload as upload
    from app.main import app
    target = tmp_path / 'passbook_counts.csv'
    exceptions = tmp_path / 'passbook_exceptions.csv'
    monkeypatch.setattr(upload, 'PASSBOOK_COUNTS', target)
    monkeypatch.setattr(upload, 'PASSBOOK_EXCEPTIONS', exceptions)
    monkeypatch.setattr(upload, 'save_source', lambda *a, **k: {})
    monkeypatch.setattr(upload, 'clear_cache', lambda: None)
    body = (b'CSP Code,CSP Name,August 2026\n'
            b'1A850001,Valid CSP,10\n'
            b'GURSEWAK GURSEWAK,,3\n')
    response = TestClient(app).post('/api/upload/passbook-printing-counts', files={'file': ('passbook.csv', body, 'text/csv')})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['validation']['exception_count'] == 1
    assert result['validation']['exception_print_count'] == 3
    valid = pd.read_csv(target)
    assert len(valid) == 1 and valid.iloc[0]['csp_id'] == '1A850001'
    ex = pd.read_csv(exceptions)
    assert len(ex) == 1 and ex.iloc[0]['csp_id'] == 'GURSEWAK GURSEWAK'
    assert ex.iloc[0]['reason'] == 'INVALID_OR_MISSING_CSP_CODE'
