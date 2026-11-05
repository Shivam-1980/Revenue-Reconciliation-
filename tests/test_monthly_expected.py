import pandas as pd
from app.services.monthly_expected import calculate_monthly_components

def test_monthly_components_from_bc_bases():
    cm=pd.DataFrame({
        'CSP Code':['C1','C2','C1','C1','C2','C3','C4','C5'],
        'Transaction Type':['ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS','MATM CASH TRANSACTIONS INCENTIVE','MATM CASH TRANSACTIONS INCENTIVE','TAB TRANSACTIONS INCENTIVE','PASSBOOK PRINTER COST REIMBURSEMENT','DFS PRIORITIES INCENTIVE','DFS PRIORITIES INCENTIVE','PENALTY FOR CSP INACTIVITY'],
        'Num Txns / Avg Bal':[10,400,100,100,1,1,4,None],
        'Commission':[10,0,0,0,610,1200,2100,1000],
    })
    # normalize source columns used by engine
    cm=cm.rename(columns={'CSP Code':'csp_id','Transaction Type':'transaction_type','Num Txns / Avg Bal':'report_base','Commission':'actual_commission'})
    x=calculate_monthly_components(cm)
    # DFS expected amount must not be derived from BC's base/slab or actual payout.
    # CM058 stays evidence-gated without a validated successful-transaction source.
    # m-ATM expected must not be calculated from the BC report's own base.
    # TAB still uses its independent source in its own reconciliation; the generic
    # monthly summary cannot certify m-ATM expected without a current-period source.
    assert x['verified_earnings']==100*5+610
    assert x['conditional_earnings']==0
    matm = next(c for c in x['components'] if c['component']=='m-ATM cash transaction incentive')
    assert matm['amount'] is None and matm['status']=='EVIDENCE REQUIRED' 
    printer = next(c for c in x['components'] if c['component']=='Passbook printer cost reimbursement')
    assert printer['amount']==610.0
    assert printer['actual_amount']==610
    assert printer['status']=='VERIFIED'
    dfs = [c for c in x['components'] if c['component'].startswith('DFS Priorities')]
    assert len(dfs)==1 and dfs[0]['amount'] is None and dfs[0]['status']=='EVIDENCE REQUIRED'


def test_dfs_expected_uses_uploaded_monthly_slab_source_not_bc_base():
    cm=pd.DataFrame({
        'csp_id':['C1','C2'],
        'transaction_type':['DFS PRIORITIES INCENTIVE','DFS PRIORITIES INCENTIVE'],
        'report_base':[4,1],
        'actual_commission':[2200,1200],
    })
    dfs={'available':True,'status':'READY','summary':{
        'expected_total':228500,'source_rows':131,'unresolved_source_rows':18
    },'rows':[]}
    x=calculate_monthly_components(cm, dfs_reconciliation=dfs)
    item=next(c for c in x['components'] if c['component']=='DFS Priorities Incentive')
    assert item['amount']==228500
    assert item['status']=='CONDITIONAL'
    assert x['verified_earnings']==0
    assert x['conditional_earnings']==228500
    assert '18 source CSP row(s) remain unresolved' in item['notes']


def test_dfs_expected_is_verified_only_when_source_ids_resolve():
    cm=pd.DataFrame({'csp_id':['C1'],'transaction_type':['DFS PRIORITIES INCENTIVE'],'report_base':[1],'actual_commission':[1200]})
    dfs={'available':True,'status':'READY','summary':{'expected_total':1200,'source_rows':1,'unresolved_source_rows':0},'rows':[]}
    x=calculate_monthly_components(cm, dfs_reconciliation=dfs)
    item=next(c for c in x['components'] if c['component']=='DFS Priorities Incentive')
    assert item['amount']==1200 and item['status']=='VERIFIED'
    assert x['verified_earnings']==1200


def test_cm060_sbi_rule_description_alias_and_monthly_cap():
    cm = pd.DataFrame({
        "csp_id": ["C1", "C1", "C2"],
        "transaction_type": [
            "Incentive on cash transactions done through m-ATMs",
            "MATM CASH TRANSACTIONS INCENTIVE",
            "Incentive on cash transactions done through m-ATMs",
        ],
        "report_base": [200, 200, 100],
        "actual_commission": [0, 0, 0],
    })
    result = calculate_monthly_components(cm)
    item = next(c for c in result["components"] if c["component"] == "m-ATM cash transaction incentive")
    # BC report base is actual-side evidence only; never derive expected from it.
    assert item["amount"] is None
    assert item["status"] == "EVIDENCE REQUIRED"
    assert item["source_rows"] == 3


def test_cm060_rule_description_alias_handles_zero_and_missing_counts():
    cm = pd.DataFrame({
        "csp_id": ["C1", "C2"],
        "transaction_type": ["Incentive on cash transactions done through m-ATMs"] * 2,
        "report_base": [0, None],
        "actual_commission": [0, 0],
    })
    result = calculate_monthly_components(cm)
    item = next(c for c in result["components"] if c["component"] == "m-ATM cash transaction incentive")
    assert item["amount"] is None
    assert item["status"] == "EVIDENCE REQUIRED"


def test_matm_expected_uses_independent_csp_source_and_monthly_cap():
    cm=pd.DataFrame({
        'csp_id':['C1','C2','C1'],
        'transaction_type':['MATM CASH TRANSACTIONS INCENTIVE']*3,
        'report_base':[10,20,5],
        'actual_commission':[30,60,15],
    })
    src=pd.DataFrame({
        'period':['2026-08','2026-08','2026-08'],
        'csp_id':['C1','C2','C3'],
        'matm_transaction_count':[5,400,1000],
        'expected_incentive':[15,1000,1000],
    })
    x=calculate_monthly_components(cm,matm_source=src)
    item=next(c for c in x['components'] if c['component']=='m-ATM cash transaction incentive')
    assert item['amount']==2015.0
    assert item['actual_amount']==105.0
    assert item['variance_actual_minus_expected']==-1910.0
    assert item['source_transaction_count']==1405
    assert item['matched_csp_controls']==2
    assert item['notes'].find('source-only CSPs=1')>=0
