from pathlib import Path
import pandas as pd
from app.services.rate_master import build_rate_master_from_workbook, calculate_expected, _canonical_commercial_type

RULE_PATH = Path(__file__).resolve().parents[1] / 'app' / 'data' / 'expected_commission_rule' / 'latest.xlsx'


def _rules():
    rules, validation = build_rate_master_from_workbook(RULE_PATH.read_bytes(), 'SBI_Expected_Commission_Rule.xlsx')
    assert validation['valid'] is True
    return rules


def test_account_opening_aliases_and_rd_map_to_permanent_rule_ids():
    assert _canonical_commercial_type('SB Account Opening: With E-KYC') == 'ACCOUNT OPPENING (PMJDY)'
    assert _canonical_commercial_type('Saving Account Opening: Without E-KYC (with OVD)') == 'ACCOUNT OPPENING (PMJDY)'
    assert _canonical_commercial_type('Opening of RD Accounts') == 'RD OPEN'
    assert _canonical_commercial_type('RD Account Opening') == 'RD OPEN'
    assert _canonical_commercial_type('Opening STDR/FD') == 'STDR OPEN'
    assert _canonical_commercial_type('Opening of STDR/FD') == 'STDR OPEN'
    assert _canonical_commercial_type('STDR/FD Open') == 'STDR OPEN'
    assert _canonical_commercial_type('Fixed Deposit Open') == 'STDR OPEN'


def test_explicit_ekyc_and_ovd_labels_select_correct_deposit_slabs():
    tx = pd.DataFrame([
        {'rule_type':'SB Account Opening: With E-KYC','csp_id':'1A850001','amount':1000,'channel':'RURAL'},
        {'rule_type':'SB Account Opening: With E-KYC','csp_id':'1A850002','amount':500,'channel':'RURAL'},
        {'rule_type':'SB Account Opening: With E-KYC','csp_id':'1A850003','amount':100,'channel':'RURAL'},
        {'rule_type':'SB Account Opening: With E-KYC','csp_id':'1A850004','amount':0,'channel':'RURAL'},
        {'rule_type':'Saving Account Opening: Without E-KYC (with OVD)','csp_id':'1A850005','amount':100,'channel':'URBAN'},
        {'rule_type':'Saving Account Opening: Without E-KYC (with OVD)','csp_id':'1A850006','amount':0,'channel':'URBAN'},
    ])
    out, _ = calculate_expected(tx, _rules())
    assert out['expected_commission'].tolist() == [50.0,40.0,30.0,20.0,10.0,5.0]
    assert out['rate_status'].eq('Applied').all()


def test_rd_and_stdr_fd_rules_use_minimum_deposit_and_geographic_caps():
    tx = pd.DataFrame([
        {'rule_type':'Opening of RD Accounts','csp_id':'1A850010','amount':50,'channel':'RURAL'},
        {'rule_type':'Opening STDR/FD','csp_id':'1A850011','amount':1000,'channel':'RURAL'},
        {'rule_type':'Opening STDR/FD','csp_id':'1A850012','amount':10000,'channel':'RURAL'},
        {'rule_type':'Opening STDR/FD','csp_id':'1A850013','amount':15000,'channel':'URBAN'},
        {'rule_type':'Opening STDR/FD','csp_id':'1A850014','amount':15000,'channel':'RURAL'},
    ])
    out, _ = calculate_expected(tx, _rules())
    assert out.loc[0,'expected_commission'] == 10.0
    assert out.loc[1,'expected_commission'] == 5.0
    assert out.loc[2,'expected_commission'] == 50.0
    assert out.loc[3,'expected_commission'] == 75.0
    assert pd.isna(out.loc[4,'expected_commission'])
    assert out.loc[4,'rate_status'] == 'Condition Failed'


def test_stdr_operational_aliases_resolve_to_same_reconciliation_key():
    from app.services.reconciliation_engine import resolve_transaction_type
    for label in ('STDR OPEN', 'Opening STDR/FD', 'Opening of STDR/FD', 'STDR/FD Open', 'Fixed Deposit Open'):
        assert resolve_transaction_type(label) == 'STDR OPEN'
