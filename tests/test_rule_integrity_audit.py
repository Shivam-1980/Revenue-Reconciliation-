import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.main import app
from app.services.rate_master import calculate_expected
from app.services.rural_commission import reconcile_rural_commission, load_txn_mapping
from fastapi.testclient import TestClient


def _rules():
    return pd.read_csv(Path(__file__).resolve().parents[1] / 'backend/app/data/rate_master/approved_rule_master_reference.csv')


def test_rd_minimum_deposit_is_enforced():
    rules = _rules()
    tx = pd.DataFrame([{
        'transaction_id':'r1','csp_id':'C1','rule_type':'RD OPEN','amount':49,
        'transaction_date':'2026-08-01','channel':'RURAL','kyc_type':''
    },{
        'transaction_id':'r2','csp_id':'C1','rule_type':'RD OPEN','amount':50,
        'transaction_date':'2026-08-01','channel':'RURAL','kyc_type':''
    }])
    out,_=calculate_expected(tx,rules)
    assert pd.isna(out.loc[0,'expected_commission'])
    assert out.loc[0,'rate_status']=='Condition Failed'
    assert out.loc[1,'expected_commission']==10


def test_stdr_caps_and_amount_limits_are_preserved():
    rules=_rules()
    tx=pd.DataFrame([
        {'transaction_id':'s1','csp_id':'C1','rule_type':'STDR OPEN','amount':10000,'transaction_date':'2026-08-01','channel':'RURAL','kyc_type':''},
        {'transaction_id':'s2','csp_id':'C2','rule_type':'STDR OPEN','amount':20000,'transaction_date':'2026-08-01','channel':'URBAN','kyc_type':''},
        {'transaction_id':'s3','csp_id':'C1','rule_type':'STDR OPEN','amount':10001,'transaction_date':'2026-08-01','channel':'RURAL','kyc_type':''},
    ])
    out,_=calculate_expected(tx,rules)
    assert out.loc[0,'expected_commission']==50
    assert out.loc[1,'expected_commission']==100
    assert pd.isna(out.loc[2,'expected_commission'])
    assert out.loc[2,'rate_status']=='Condition Failed'


def test_mini_statement_cap_is_evidence_gated_without_account_id():
    rules=_rules()
    tx=pd.DataFrame([{'transaction_id':'m1','csp_id':'C1','rule_type':'MATM MINI STATEMENT','amount':0,'transaction_date':'2026-08-01','channel':'RURAL','kyc_type':''}])
    out,_=calculate_expected(tx,rules)
    assert out.loc[0,'expected_commission']==2
    assert bool(out.loc[0,'required_evidence_missing']) is True
    assert out.loc[0,'rate_status']=='Evidence Required'


def test_api_version_is_release_version_without_internal_rule_number():
    data=TestClient(app).get('/api/version').json()
    assert data['version']=='62.6.164-clean-state-every-start'
    assert 'rule-9' not in data['version'].lower()

def test_every_catalog_rule_is_present_in_executable_master_and_status_is_preserved():
    root=Path(__file__).resolve().parents[1]
    cat=pd.read_csv(root/'docs/SBI_RULE_CATALOG.csv',dtype=str).fillna('')
    rm=pd.read_csv(root/'backend/app/data/rate_master/approved_rule_master_reference.csv',dtype=str).fillna('')
    assert set(cat['rule_id']).issubset(set(rm['rule_id']))
    assert len(cat)==125
    assert len(rm)==127
    confirmed=rm[rm['rule_status'].str.upper().eq('CONFIRMED')]
    assert confirmed['rate'].ne('').all()
    # Every non-confirmed rule remains visible but is not silently promoted.
    assert set(cat.loc[cat['rule_status'].str.upper().eq('MAPPING TO CONFIRM'),'rule_id']).issubset(set(rm.loc[rm['rule_status'].str.upper().eq('MAPPING TO CONFIRM'),'rule_id']))
