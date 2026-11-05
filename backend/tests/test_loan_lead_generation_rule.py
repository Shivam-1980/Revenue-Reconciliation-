from app.api.upload import _loan_lead_product

def test_loan_lead_product_rates_are_not_conflated():
    assert _loan_lead_product("HOUSING_LOAN_LEAD") == "HOME LOAN"
    assert _loan_lead_product("OTHER_P_SEG_LOAN_LEAD") is None  # ambiguous source label; do not guess Gold Loan
    assert _loan_lead_product("AGRI_LOAN_LEAD") is None  # broader product than SBI Agri Gold Loan
    assert _loan_lead_product("AGRI_GOLD_LOAN_LEAD") == "AGRI GOLD LOAN"

def test_unknown_product_not_guessed():
    assert _loan_lead_product("OTHER_UNLISTED_LOAN") is None

from app.services.loan_lead_reconciliation import build_reconciliation, actual_loan_product, infer_periods
import pandas as pd


def test_actual_loan_lead_payout_mapping_is_explicit_and_period_scoped():
    assert actual_loan_product('P SEGMENT GOLD LOAN LEAD GENERATION') == 'P-SEGMENT GOLD LOAN'
    assert actual_loan_product('PERSONAL LOAN LEAD GENERATION') == 'PERSONAL LOAN'
    assert actual_loan_product('LOAN DEPOSIT') is None
    assert infer_periods('BC Report - Full - AUG-26.xlsx') == ['2026-08']


def test_count_matching_does_not_falsely_certify_commission_amount():
    leads = pd.DataFrame([
        {'period':'2026-08','lead_id':'L1','csp_id':'1A859004','loan_product':'P-SEGMENT GOLD LOAN','status':'Post Sanctioned Documentation','sanction_limit':None,'expected_base_commission':None},
        {'period':'2026-08','lead_id':'L2','csp_id':'1A859003','loan_product':'P-SEGMENT GOLD LOAN','status':'Post Sanctioned Documentation','sanction_limit':None,'expected_base_commission':None},
        {'period':'2026-08','lead_id':'L3','csp_id':'1A859003','loan_product':'P-SEGMENT GOLD LOAN','status':'Post Sanctioned Documentation','sanction_limit':None,'expected_base_commission':None},
    ])
    bc = pd.DataFrame([
        {'csp_id':'1A859004','transaction_type':'P SEGMENT GOLD LOAN LEAD GENERATION','actual_commission':118,'report_base':1},
        {'csp_id':'1A859003','transaction_type':'P SEGMENT GOLD LOAN LEAD GENERATION','actual_commission':236,'report_base':2},
        {'csp_id':'1A859002','transaction_type':'P SEGMENT GOLD LOAN LEAD GENERATION','actual_commission':118,'report_base':1},
    ])
    result = build_reconciliation(leads, bc, {'filename':'BC Report - AUG-26.xlsx'})
    assert result['summary']['actual_commission_total'] == 472.0
    by_csp = {r['csp_id']:r for r in result['match_rows']}
    assert by_csp['1A859004']['status'] == 'COUNT_MATCH_AMOUNT_UNVERIFIED'
    assert by_csp['1A859003']['status'] == 'COUNT_MATCH_AMOUNT_UNVERIFIED'
    assert by_csp['1A859002']['status'] == 'ACTUAL_WITHOUT_ELIGIBLE_LEAD'
    assert result['status'] == 'PROVISIONAL'
    assert by_csp['1A859004']['variance'] is None


def test_period_mismatch_does_not_join_actual_commission():
    leads = pd.DataFrame([{'period':'2026-09','lead_id':'L1','csp_id':'1A859004','loan_product':'P-SEGMENT GOLD LOAN','status':'Post Sanctioned Documentation','sanction_limit':None,'expected_base_commission':None}])
    bc = pd.DataFrame([{'csp_id':'1A859004','transaction_type':'P SEGMENT GOLD LOAN LEAD GENERATION','actual_commission':118,'report_base':1}])
    result = build_reconciliation(leads, bc, {'filename':'BC Report - AUG-26.xlsx'})
    assert result['summary']['actual_commission_total'] is None
    assert result['match_rows'][0]['status'] == 'PERIOD_UNVERIFIED'


def test_exact_commission_match_requires_sanction_base_and_explicit_gst():
    leads = pd.DataFrame([{
        'period':'2026-08','lead_id':'L1','csp_id':'1A850001','loan_product':'HOME LOAN',
        'status':'Sanctioned','sanction_limit':20000,'expected_base_commission':100.0,
        'gst_rate':18.0,'gst_amount':18.0,
    }])
    bc = pd.DataFrame([{
        'csp_id':'1A850001','transaction_type':'HOME LOAN LEAD GENERATION',
        'actual_commission':118.0,'report_base':1,
    }])
    result = build_reconciliation(leads, bc, {'filename':'BC Report - AUG-26.xlsx'})
    assert result['match_rows'][0]['status'] == 'MATCHED'
    assert result['match_rows'][0]['expected_total_commission_including_gst'] == 118.0
    assert result['match_rows'][0]['variance'] == 0.0
    assert result['status'] == 'READY'


def test_base_only_expected_amount_is_not_certified_when_gst_unknown():
    leads = pd.DataFrame([{
        'period':'2026-08','lead_id':'L1','csp_id':'1A850001','loan_product':'HOME LOAN',
        'status':'Sanctioned','sanction_limit':20000,'expected_base_commission':100.0,
        'gst_rate':None,'gst_amount':None,
    }])
    bc = pd.DataFrame([{
        'csp_id':'1A850001','transaction_type':'HOME LOAN LEAD GENERATION',
        'actual_commission':100.0,'report_base':1,
    }])
    result = build_reconciliation(leads, bc, {'filename':'BC Report - AUG-26.xlsx'})
    assert result['match_rows'][0]['status'] == 'COUNT_MATCH_GST_TREATMENT_UNVERIFIED'
    assert result['match_rows'][0]['variance'] is None
    assert result['status'] == 'PROVISIONAL'


def test_expected_total_mismatch_is_an_exception_not_a_match():
    leads = pd.DataFrame([{
        'period':'2026-08','lead_id':'L1','csp_id':'1A850001','loan_product':'HOME LOAN',
        'status':'Sanctioned','sanction_limit':20000,'expected_base_commission':100.0,
        'gst_rate':18.0,'gst_amount':18.0,
    }])
    bc = pd.DataFrame([{
        'csp_id':'1A850001','transaction_type':'HOME LOAN LEAD GENERATION',
        'actual_commission':120.0,'report_base':1,
    }])
    result = build_reconciliation(leads, bc, {'filename':'BC Report - AUG-26.xlsx'})
    assert result['match_rows'][0]['status'] == 'AMOUNT_MISMATCH'
    assert result['match_rows'][0]['variance'] == 2.0
    assert result['status'] == 'PROVISIONAL'


def test_unmapped_products_are_reported_explicitly_in_summary():
    leads = pd.DataFrame([{
        'period':'2026-08','lead_id':'L1','csp_id':'1A850001','loan_product':None,
        'status':'New Lead','sanction_limit':None,'expected_base_commission':None,
    }])
    result = build_reconciliation(leads, pd.DataFrame(), {})
    assert result['summary']['product_counts'] == {'UNMAPPED': 1}
    assert result['summary']['unmapped_product_rows'] == 1


def test_sanctioned_unmapped_product_is_visible_as_control_exception():
    leads = pd.DataFrame([{
        'period':'2026-08','lead_id':'L1','csp_id':'1A850001','loan_product':None,
        'loan_type_raw':'OTHER_P_SEG_LOAN_LEAD','status':'Post Sanctioned Documentation',
        'sanction_limit':None,'expected_base_commission':None,'gst_amount':None,
    }])
    result = build_reconciliation(leads, pd.DataFrame(), {'filename':'BC Report - AUG-26.xlsx'})
    assert len(result['match_rows']) == 1
    assert result['match_rows'][0]['status'] == 'PRODUCT_MAPPING_REQUIRED'
    assert result['summary']['unmapped_eligible_control_groups'] == 1
    assert result['status'] == 'PROVISIONAL'


def test_missing_actual_reported_units_is_not_mislabeled_as_count_mismatch():
    leads = pd.DataFrame([{
        'period':'2026-08','lead_id':'L1','csp_id':'1A850001','loan_product':'HOME LOAN',
        'status':'Sanctioned','sanction_limit':20000,'expected_base_commission':100.0,
        'gst_rate':18.0,'gst_amount':18.0,
    }])
    bc = pd.DataFrame([{
        'csp_id':'1A850001','transaction_type':'HOME LOAN LEAD GENERATION',
        'actual_commission':118.0,'report_base':None,
    }])
    result = build_reconciliation(leads, bc, {'filename':'BC Report - AUG-26.xlsx'})
    assert result['match_rows'][0]['status'] == 'COUNT_UNVERIFIED'
    assert result['match_rows'][0]['variance'] == 0.0
    assert result['status'] == 'PROVISIONAL'
