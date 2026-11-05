import pandas as pd
from app.services.rural_commission import reconcile_rural_commission, load_txn_mapping


def test_rural_rule_is_deterministic_and_not_august_specific():
    master = pd.DataFrame([
        {'csp_id':'1A850001','csp_name':'A','csp_category':'Basic','relationship_manager':'RM','login_days':20,'period':'2026-09'},
        {'csp_id':'1A850002','csp_name':'B','csp_category':'Basic','relationship_manager':'RM','login_days':19,'period':'2026-09'},
        {'csp_id':'1A850003','csp_name':'C','csp_category':'Basic','relationship_manager':'RM','login_days':25,'period':'2026-09'},
    ])
    commission = pd.DataFrame([
        {'csp_id':'1A850001','transaction_type':'AEPS ONUS WITHDRAWAL','report_base':100,'actual_commission':1000,'channel':'RURAL'},
        {'csp_id':'1A850001','transaction_type':'RURAL COMMISSION','report_base':None,'actual_commission':2000,'channel':'RURAL'},
        {'csp_id':'1A850002','transaction_type':'AEPS ONUS WITHDRAWAL','report_base':200,'actual_commission':1000,'channel':'RURAL'},
        {'csp_id':'1A850002','transaction_type':'RURAL COMMISSION','report_base':None,'actual_commission':2000,'channel':'RURAL'},
        {'csp_id':'1A850003','transaction_type':'ACC OPEN WITH EKYC AND INIT DEP BELOW 100','report_base':50,'actual_commission':1000,'channel':'RURAL'},
    ])
    mapping = load_txn_mapping()
    result = reconcile_rural_commission(commission, transaction_month='2026-09', rural_master=master, txn_mapping=mapping)
    assert result['available'] is True
    assert result['summary']['eligible_csp_count'] == 2
    assert result['summary']['expected_commission'] == 4000
    assert result['summary']['short_paid_amount'] == 2000
    assert result['summary']['excess_paid_amount'] == 2000
    rows = {r['csp_id']: r for r in result['rows']}
    assert rows['1A850001']['eligible'] is True
    assert rows['1A850002']['eligible'] is False
    assert rows['1A850003']['eligible'] is True
    assert rows['1A850003']['pmjdy_count'] == 50


def test_rural_rule_requires_current_period_source():
    master = pd.DataFrame([{'csp_id':'1A850001','csp_name':'A','csp_category':'Basic','relationship_manager':'RM','login_days':20,'period':'2026-08'}])
    commission = pd.DataFrame([{'csp_id':'1A850001','transaction_type':'RURAL COMMISSION','report_base':None,'actual_commission':2000,'channel':'RURAL'}])
    result = reconcile_rural_commission(commission, transaction_month='2026-09', rural_master=master, txn_mapping=load_txn_mapping())
    assert result['available'] is False
    assert result['status'] == 'PERIOD_MISMATCH'


def test_sbi_rule_9_requires_both_conditions_and_uses_or_inside_condition_2():
    master = pd.DataFrame([
        {'csp_id':'1A850011','csp_name':'PMJDY','csp_category':'RURAL','relationship_manager':'RM','login_days':20,'period':'2026-10'},
        {'csp_id':'1A850012','csp_name':'TXN','csp_category':'RURAL','relationship_manager':'RM','login_days':21,'period':'2026-10'},
        {'csp_id':'1A850013','csp_name':'LOGINFAIL','csp_category':'RURAL','relationship_manager':'RM','login_days':19,'period':'2026-10'},
        {'csp_id':'1A850014','csp_name':'NEITHER','csp_category':'RURAL','relationship_manager':'RM','login_days':25,'period':'2026-10'},
    ])
    commission = pd.DataFrame([
        {'csp_id':'1A850011','transaction_type':'ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE','report_base':50,'actual_commission':2000,'channel':'RURAL'},
        {'csp_id':'1A850012','transaction_type':'AEPS ONUS WITHDRAWAL','report_base':100,'actual_commission':2000,'channel':'RURAL'},
        {'csp_id':'1A850013','transaction_type':'AEPS ONUS WITHDRAWAL','report_base':100,'actual_commission':2000,'channel':'RURAL'},
        {'csp_id':'1A850014','transaction_type':'AEPS ONUS WITHDRAWAL','report_base':99,'actual_commission':2000,'channel':'RURAL'},
    ])
    result = reconcile_rural_commission(commission, transaction_month='2026-10', rural_master=master, txn_mapping=load_txn_mapping())
    rows = {r['csp_id']: r for r in result['rows']}
    assert result['summary']['rule_code'] == 'SBI-RULE-9'
    assert result['summary']['incentive_amount'] == 2000
    assert rows['1A850011']['eligible'] is True and rows['1A850011']['pmjdy_eligible'] is True
    assert rows['1A850012']['eligible'] is True and rows['1A850012']['txn_eligible'] is True
    assert rows['1A850013']['eligible'] is False  # Condition 1 fails despite 100 TXN
    assert rows['1A850014']['eligible'] is False  # Condition 2 fails
