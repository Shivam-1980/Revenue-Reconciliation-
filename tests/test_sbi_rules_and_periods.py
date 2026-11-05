import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.services.rate_master import build_rate_master_from_workbook, calculate_expected
from app.services.time_reconciliation import time_reconciliation

MASTER = ROOT / 'docs' / 'approved_master' / 'SBI_CSP_Final_Commission.xlsx'


def load_rules():
    assert MASTER.exists(), f'Missing test master: {MASTER}'
    return build_rate_master_from_workbook(MASTER.read_bytes(), MASTER.name)


def test_sbi_master_has_fixed_percentage_rules_and_blocks_unapproved_mappings():
    rules, meta = load_rules()
    assert meta['valid'] is True
    assert meta['transaction_rules'] > 0
    assert 'ACCOUNT OPPENING (PMJDY)' in set(rules.transaction_type)
    assert 'CASH WITHDRAWAL' in set(rules.transaction_type)
    assert 'STDR OPEN' in set(rules.transaction_type)
    assert (rules.rate_type == 'PERCENTAGE').any()
    assert (rules.rate_type == 'FIXED').any()
    # Product mappings marked 'Mapping to confirm' are calculable for control
    # purposes but remain provisional; final settlement is still blocked until
    # those mappings are approved.
    assert rules.transaction_type.isin(['IMPS FUNDTRANFER', 'IMPS MONEY TRANSFER']).any()
    assert any('Mapping to confirm' in w for w in meta['warnings'])


def test_representative_sbi_calculations():
    rules, _ = load_rules()
    tx = pd.DataFrame([
        {'transaction_id':'a','csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':1000,'transaction_date':'2026-09-01','channel':'','kyc_type':'E-KYC'},
        {'transaction_id':'b','csp_id':'C1','rule_type':'CASH WITHDRAWAL','amount':8000,'transaction_date':'2026-09-01','channel':'RURAL'},
        {'transaction_id':'c','csp_id':'C1','rule_type':'STDR OPEN','amount':8000,'transaction_date':'2026-09-01','channel':'RURAL'},
    ])
    out, _ = calculate_expected(tx, rules)
    vals = dict(zip(out.transaction_id, out.expected_commission))
    assert vals['a'] == 50.0
    assert vals['b'] == 15.0
    assert vals['c'] == 40.0


def test_day_and_month_reconciliation_spans_multiple_months_without_fake_allocation():
    rules, _ = load_rules()
    tx = pd.DataFrame([
        {'transaction_id':'1','csp_id':'C1','transaction_type':'INITIAL DEPOSIT','amount':1000,'transaction_date':'2026-08-01','status':'SUCCESS','kyc_type':'E-KYC'},
        {'transaction_id':'2','csp_id':'C1','transaction_type':'INITIAL DEPOSIT','amount':1000,'transaction_date':'2026-09-03','status':'SUCCESS','kyc_type':'E-KYC'},
    ])
    cm = pd.DataFrame([
        {'csp_id':'C1','transaction_type':'ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE','actual_commission':50,'report_base':1,'commission_date':'2026-08-01'},
        {'csp_id':'C1','transaction_type':'ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE','actual_commission':50,'report_base':1,'commission_date':'2026-09-03'},
    ])
    daily = time_reconciliation(tx, cm, rules, grain='day')
    monthly = time_reconciliation(tx, cm, rules, grain='month')
    assert daily['period'].tolist() == ['2026-08-01', '2026-09-03']
    assert monthly['period'].tolist() == ['2026-08', '2026-09']
    assert daily['variance'].tolist() == [0.0, 0.0]
    assert monthly['variance'].tolist() == [0.0, 0.0]



def test_missing_geography_is_not_assumed_even_when_current_amount_happens_to_share_a_payout():
    rules, _ = load_rules()
    tx = pd.DataFrame([
        {'transaction_id':'1','csp_id':'C1','rule_type':'CASH WITHDRAWAL','amount':3000,'transaction_date':'2026-09-03','channel':''},
    ])
    out, _ = calculate_expected(tx, rules)
    assert pd.isna(out.iloc[0]['expected_commission'])
    assert out.iloc[0]['rate_status'] == 'Geography Required'


def test_missing_geography_does_not_fake_expected_commission():
    rules, _ = load_rules()
    tx = pd.DataFrame([
        {'transaction_id':'1','csp_id':'C1','transaction_type':'Withdrawal','amount':8000,'transaction_date':'2026-09-03','status':'SUCCESS'},
    ])
    cm = pd.DataFrame([
        {'csp_id':'C1','transaction_type':'CASH WITHDRAWAL','actual_commission':15,'report_base':1,'commission_date':'2026-09-03'},
    ])
    out = time_reconciliation(tx, cm, rules, grain='day')
    assert float(out.iloc[0]['coverage_pct']) == 0.0
    assert pd.isna(out.iloc[0]['variance'])
    assert out.iloc[0]['reconciliation_status'] == 'Unresolved Coverage'


def test_success_source_is_not_month_or_sheet_specific():
    import pandas as pd
    from app.services.validator import validate_transaction_data
    from app.services.file_processor import normalize_columns
    from app.services.number_parser import parse_date_series

    # Arbitrary sheet/export: no Status column because it is already a
    # success-only extract. Different dates and an Excel serial date are valid.
    df=pd.DataFrame({
        'Reference Number':['R1','R2','R3'],
        'CSP Code':['C1','C1','C2'],
        'Transaction Type':['WITHDRAWAL','WITHDRAWAL','DEPOSIT'],
        'Amount':['1,000','2000','3000'],
        'Transaction Date':['15-01-2026','2026/02/20',46000],
    })
    std,v=validate_transaction_data(normalize_columns(df))
    assert v['valid'] is True
    assert v['status_assumed_success'] is True
    assert v['processable_rows']==3
    parsed=parse_date_series(std['transaction_date'])
    assert parsed.notna().all()
    assert parsed.iloc[0].date().isoformat()=='2026-01-15'
    assert parsed.iloc[1].date().isoformat()=='2026-02-20'


def test_v54_supplied_pmjdy_and_social_security_rules():
    rules, _ = load_rules()
    tx = pd.DataFrame([
        {'transaction_id':'d1','csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':50,'transaction_date':'2026-08-01','channel':''},
        {'transaction_id':'d2','csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':100,'transaction_date':'2026-08-01','channel':''},
        {'transaction_id':'d3','csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':500,'transaction_date':'2026-08-01','channel':''},
        {'transaction_id':'d4','csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':1000,'transaction_date':'2026-08-01','channel':''},
        {'transaction_id':'p1','csp_id':'C1','rule_type':'PMJJBY','amount':436,'transaction_date':'2026-08-01','channel':''},
        {'transaction_id':'p2','csp_id':'C1','rule_type':'PMJJBY','amount':342,'transaction_date':'2026-09-01','channel':''},
        {'transaction_id':'p3','csp_id':'C1','rule_type':'PMJJBY','amount':228,'transaction_date':'2026-12-01','channel':''},
        {'transaction_id':'p4','csp_id':'C1','rule_type':'PMJJBY','amount':114,'transaction_date':'2026-03-01','channel':''},
        {'transaction_id':'s1','csp_id':'C1','rule_type':'PMSBY','amount':20,'transaction_date':'2026-08-01','channel':''},
    ])
    out, _ = calculate_expected(tx, rules)
    vals = dict(zip(out.transaction_id, out.expected_commission))
    assert all(pd.isna(vals[k]) for k in ['d1','d2','d3','d4'])
    assert vals == {**{k:vals[k] for k in ['d1','d2','d3','d4']}, 'p1':30.0,'p2':22.5,'p3':15.0,'p4':7.5,'s1':1.0}


def test_sbi_v55_account_opening_kyc_rules_and_pmjjby_rates():
    import pandas as pd
    from app.services.rate_master import calculate_expected
    rules = pd.DataFrame([
        {'rule_id':'CM001','transaction_type':'ACCOUNT OPPENING (PMJDY)','rate':50.0,'rate_type':'FIXED','min_amount':1000.0,'max_amount':pd.NA,'max_exclusive':False,'min_exclusive':False,'allowed_months':'','kyc_requirement':'EKYC','commercial_scope':'TRANSACTION','priority':100,'rule_status':'CONFIRMED'},
        {'rule_id':'CM004','transaction_type':'ACCOUNT OPPENING (PMJDY)','rate':20.0,'rate_type':'FIXED','min_amount':pd.NA,'max_amount':100.0,'max_exclusive':True,'min_exclusive':False,'allowed_months':'','kyc_requirement':'EKYC','commercial_scope':'TRANSACTION','priority':100,'rule_status':'CONFIRMED'},
        {'rule_id':'CM005','transaction_type':'ACCOUNT OPPENING (PMJDY)','rate':10.0,'rate_type':'FIXED','min_amount':100.0,'max_amount':pd.NA,'max_exclusive':False,'min_exclusive':False,'allowed_months':'','kyc_requirement':'OVD','commercial_scope':'TRANSACTION','priority':100,'rule_status':'CONFIRMED'},
        {'rule_id':'CM006','transaction_type':'ACCOUNT OPPENING (PMJDY)','rate':5.0,'rate_type':'FIXED','min_amount':pd.NA,'max_amount':100.0,'max_exclusive':True,'min_exclusive':False,'allowed_months':'','kyc_requirement':'OVD','commercial_scope':'TRANSACTION','priority':100,'rule_status':'CONFIRMED'},
        {'rule_id':'PMJJBY-Q2','transaction_type':'PMJJBY','rate':22.5,'rate_type':'FIXED','min_amount':pd.NA,'max_amount':pd.NA,'max_exclusive':False,'min_exclusive':False,'allowed_months':'9,10,11','kyc_requirement':'','commercial_scope':'TRANSACTION','priority':100,'rule_status':'CONFIRMED'},
        {'rule_id':'PMJJBY-Q4','transaction_type':'PMJJBY','rate':7.5,'rate_type':'FIXED','min_amount':pd.NA,'max_amount':pd.NA,'max_exclusive':False,'min_exclusive':False,'allowed_months':'3,4,5','kyc_requirement':'','commercial_scope':'TRANSACTION','priority':100,'rule_status':'CONFIRMED'},
    ])
    tx = pd.DataFrame([
        {'csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':1500,'transaction_date':'2026-08-10','kyc_type':'E-KYC'},
        {'csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':1500,'transaction_date':'2026-08-10','kyc_type':'OVD'},
        {'csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':50,'transaction_date':'2026-08-10','kyc_type':'OVD'},
        {'csp_id':'C1','rule_type':'ACCOUNT OPPENING (PMJDY)','amount':1500,'transaction_date':'2026-08-10','kyc_type':''},
        {'csp_id':'C1','rule_type':'PMJJBY','amount':342,'transaction_date':'2026-10-10','kyc_type':''},
        {'csp_id':'C1','rule_type':'PMJJBY','amount':114,'transaction_date':'2026-04-10','kyc_type':''},
    ])
    out,_ = calculate_expected(tx,rules)
    assert out.loc[0,'expected_commission'] == 50.0
    assert out.loc[1,'expected_commission'] == 10.0
    assert out.loc[2,'expected_commission'] == 5.0
    assert pd.isna(out.loc[3,'expected_commission'])
    assert out.loc[4,'expected_commission'] == 22.5
    assert out.loc[5,'expected_commission'] == 7.5


def test_stdr_commission_caps_are_preserved_from_sbi_master():
    rules, _ = load_rules()
    tx = pd.DataFrame([
        {'transaction_id':'r1','csp_id':'C1','rule_type':'STDR OPEN','amount':10000,'transaction_date':'2026-08-01','channel':'RURAL'},
        {'transaction_id':'r2','csp_id':'C1','rule_type':'STDR OPEN','amount':20000,'transaction_date':'2026-08-01','channel':'URBAN'},
    ])
    out, _ = calculate_expected(tx, rules)
    vals = dict(zip(out.transaction_id, out.expected_commission))
    assert vals['r1'] == 50.0
    assert vals['r2'] == 100.0


def test_normalized_reference_csv_rate_master_validates_and_preserves_scope():
    from pathlib import Path
    import pandas as pd
    from app.services.rate_master import validate_rate_master
    path = Path(__file__).resolve().parents[1] / 'backend' / 'app' / 'data' / 'rate_master' / 'approved_rule_master_reference.csv'
    normalized, result = validate_rate_master(pd.read_csv(path, low_memory=False))
    assert result['valid'] is True, result
    assert len(normalized) == 127
    assert (normalized['commercial_scope'] == 'TRANSACTION').sum() == 126
    assert 'FEE_PERCENTAGE' in set(normalized['rate_type'])
    assert (normalized['rule_status'] == 'MAPPING TO CONFIRM').sum() == 52
