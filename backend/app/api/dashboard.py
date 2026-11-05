from pathlib import Path
import pandas as pd
from fastapi import APIRouter
from app.api.reconciliation import load_result,RM,CM,social_security,passbook_printing
from app.services.upload_metadata import load_metadata
from app.services.monthly_expected import calculate_monthly_components
from app.services.rural_commission import load_rural_master, load_txn_mapping, reconcile_rural_commission, RURAL_MASTER_PATH
from app.services.number_parser import parse_date_series
from app.services.fast_text import on_unique, stripped_upper
from app.services.transaction_processor import get_successful_transactions
from app.services.control_kpi import controlled_reconciliation_kpi,all_source_control_kpi,safe_dfs_headline_controls,rural_control_group_count,all_source_kpi_status,resolved_dfs_headline_controls
import math
import numpy as np

router=APIRouter()

def _penalty_assessment(cm: pd.DataFrame, tx: pd.DataFrame, meta: dict):
    """Return only penalties that are actually evidenced by the uploaded sources.

    The SBI master contains CM075 (Inactivity Penalty): Rs 1,000 per qualifying
    CSP/month for the stated inactivity/onboarding condition. The transaction and
    BC aggregate files do not contain inactivity/onboarding/visit evidence, so the
    rule must not be applied merely because a CSP has low or zero transaction count.
    If the BC source explicitly contains penalty rows, those are reported as an
    observed penalty amount. Otherwise the UI clearly says the amount is not
    calculable from the current reconciliation sources.
    """
    cols=[str(c) for c in cm.columns]
    penalty_cols=[c for c in cols if any(k in c.lower() for k in ('penalty','penal','fine'))]
    explicit_total=0.0; explicit_rows=0
    # Prefer explicit numeric penalty fields. If the workbook does not expose
    # such a field, fall back to penalty-labelled transaction rows. Never add both
    # representations because the same deduction can appear in both places.
    if penalty_cols:
        for c in penalty_cols:
            vals=pd.to_numeric(cm[c],errors='coerce')
            mask=vals.notna() & vals.ne(0)
            explicit_total += float(vals[mask].abs().sum())
            explicit_rows += int(mask.sum())
    elif 'transaction_type' in cm.columns:
        tt=cm['transaction_type'].astype('string').str.upper()
        mask=tt.str.contains('PENAL|INACTIV|FINE|DEDUCTION',regex=True,na=False)
        vals=pd.to_numeric(cm.get('actual_commission'),errors='coerce')
        if mask.any():
            p=mask & vals.notna() & vals.ne(0)
            explicit_total += float(vals[p].abs().sum())
            explicit_rows += int(p.sum())

    return {
        'amount': round(explicit_total,2) if explicit_rows else None,
        'status': 'Calculated from BC source' if explicit_rows else 'Not calculable from current sources',
        'source': (meta.get('commission') or {}).get('filename') if explicit_rows else 'SBI Commission Master + penalty evidence required',
        'rule': 'CM075 — Inactivity Penalty: ₹1,000 per qualifying CSP/month when the stated 30-day inactivity/onboarding condition is met.',
        'evidence_required': 'Current transaction/BC sheets do not contain CSP inactivity-days or onboarding-status evidence. A zero/low transaction count is not treated as proof of inactivity.',
        'rows': explicit_rows,
        'is_verified': bool(explicit_rows),
    }



def _successful_transaction_type_source_summary():
    """Return the authoritative transaction-type summary directly from the uploaded
    Successful Transaction source. This view intentionally does not use the
    reconciliation cache, BC report joins, rate rules, or mapped transaction names
    so the dashboard cannot lose source rows because of a reconciliation rule.
    """
    tx_path = Path(__file__).resolve().parents[1] / 'data' / 'transactions' / 'latest_transactions.csv'
    if not tx_path.exists():
        return []
    from app.services.transaction_processor import load_successful_transactions
    tx = load_successful_transactions(tx_path)
    if tx.empty:
        return []
    tx['transaction_type'] = stripped_upper(tx['transaction_type'])
    tx['csp_id'] = stripped_upper(tx['csp_id'])
    tx['amount'] = pd.to_numeric(tx['amount'], errors='coerce')
    out = tx.groupby('transaction_type', dropna=False).agg(
        successful_transactions=('transaction_type','size'),
        transaction_amount=('amount', lambda x: pd.to_numeric(x, errors='coerce').sum(min_count=1)),
        unique_csps=('csp_id','nunique')
    ).reset_index()
    out = out.sort_values(['successful_transactions','transaction_type'], ascending=[False, True]).reset_index(drop=True)
    return out.to_dict(orient='records')


def _initial_deposit_conditional_summary_from_transactions(tx: pd.DataFrame):
    """Calculate amount slabs while keeping KYC-dependent commission conditional."""
    empty = {'status':'NO_INITIAL_DEPOSIT_ROWS','successful_transactions':0,'unique_csps':0,
             'amount_total':0.0,'slabs':[], 'conditional_ekyc_total':None,
             'conditional_ovd_total':None,'verified_expected_commission':None,'csp_summary':[],
             'note':'No successful Initial Deposit rows exist in the current uploaded source.'}
    if tx is None or tx.empty or not {'transaction_type','amount','csp_id'}.issubset(tx.columns):
        return empty
    typ = on_unique(tx['transaction_type'].astype('string').fillna(''), lambda x: x.str.strip().str.upper())
    tx = tx.loc[typ.eq('INITIAL DEPOSIT')].copy()
    if tx.empty:
        return empty
    tx['_amount'] = pd.to_numeric(tx['amount'], errors='coerce')
    tx = tx[tx['_amount'].notna() & tx['_amount'].ge(0)].copy()
    a = tx['_amount']
    definitions = [
        ('BELOW_100','Below ₹100',a.lt(100),20.0,5.0),
        ('100_TO_499','₹100–₹499.99',a.ge(100)&a.lt(500),30.0,10.0),
        ('500_TO_999','₹500–₹999.99',a.ge(500)&a.lt(1000),40.0,10.0),
        ('1000_PLUS','₹1,000 and above',a.ge(1000),50.0,10.0),
    ]
    slabs=[]; ekyc_total=0.0; ovd_total=0.0
    # CSP-level control population; KYC/OVD scenarios remain conditional.
    tx['_csp_key'] = on_unique(tx['csp_id'].astype('string').fillna(''), lambda x: x.str.strip().str.upper())
    tx.loc[tx['_csp_key'].isin(['', 'NAN', 'NONE', '<NA>']), '_csp_key'] = 'MISSING_CSP_ID'
    tx['_slab_key'] = 'BELOW_100'
    tx.loc[a.ge(100) & a.lt(500), '_slab_key'] = '100_TO_499'
    tx.loc[a.ge(500) & a.lt(1000), '_slab_key'] = '500_TO_999'
    tx.loc[a.ge(1000), '_slab_key'] = '1000_PLUS'
    csp_summary=[]
    for csp, group in tx.groupby('_csp_key', dropna=False, sort=True):
        counts=group['_slab_key'].value_counts()
        csp_summary.append({'csp_id':str(csp), 'successful_transactions':int(len(group)),
            'deposit_amount':round(float(group['_amount'].sum()),2),
            'below_100_count':int(counts.get('BELOW_100',0)),
            '100_to_499_count':int(counts.get('100_TO_499',0)),
            '500_to_999_count':int(counts.get('500_TO_999',0)),
            '1000_plus_count':int(counts.get('1000_PLUS',0)),
            'conditional_ekyc_commission':round(float(sum({'BELOW_100':20,'100_TO_499':30,'500_TO_999':40,'1000_PLUS':50}[k] * int(counts.get(k,0)) for k in ['BELOW_100','100_TO_499','500_TO_999','1000_PLUS'])),2),
            'conditional_ovd_commission':round(float(sum({'BELOW_100':5,'100_TO_499':10,'500_TO_999':10,'1000_PLUS':10}[k] * int(counts.get(k,0)) for k in ['BELOW_100','100_TO_499','500_TO_999','1000_PLUS'])),2),
            'condition_status':'CONDITIONAL_KYC_EVIDENCE_REQUIRED'})
    for key,label,mask,ekyc_rate,ovd_rate in definitions:
        part=tx.loc[mask]; count=len(part)
        e=round(count*ekyc_rate,2); o=round(count*ovd_rate,2)
        ekyc_total += e; ovd_total += o
        slabs.append({'slab_key':key,'label':label,'transactions':int(count),
                      'unique_csps':int(stripped_upper(part['csp_id']).nunique()),
                      'deposit_amount':round(float(part['_amount'].sum()),2),
                      'ekyc_rate_per_eligible_account':ekyc_rate,'conditional_ekyc_commission':e,
                      'ovd_rate_per_eligible_account':ovd_rate,'conditional_ovd_commission':o})
    return {'status':'CONDITIONAL_KYC_EVIDENCE_REQUIRED','successful_transactions':int(len(tx)),
            'unique_csps':int(stripped_upper(tx['csp_id']).nunique()),
            'amount_total':round(float(tx['_amount'].sum()),2),'slabs':slabs,
            'conditional_ekyc_total':round(ekyc_total,2),'conditional_ovd_total':round(ovd_total,2),
            'verified_expected_commission':None,'csp_summary':csp_summary,
            'note':'Scenario totals only: KYC/OVD status is absent from the transaction source. These values are not verified payable commission and are excluded from settlement variance/KPIs until account-level evidence identifies the applicable rule.'}


def _initial_deposit_conditional_summary():
    """Read current uploaded source and expose non-settlement Initial Deposit scenarios."""
    path = Path(__file__).resolve().parents[1] / 'data' / 'transactions' / 'latest_transactions.csv'
    if not path.exists():
        return {'status':'SOURCE_NOT_AVAILABLE','successful_transactions':0,'unique_csps':0,
                'amount_total':0.0,'slabs':[], 'conditional_ekyc_total':None,
                'conditional_ovd_total':None,'verified_expected_commission':None,
                'note':'Upload a successful transaction source to calculate Initial Deposit amount slabs.'}
    try:
        from app.services.transaction_processor import load_successful_transactions
        return _initial_deposit_conditional_summary_from_transactions(load_successful_transactions(path))
    except Exception as exc:
        return {'status':'CALCULATION_ERROR','successful_transactions':0,'unique_csps':0,
                'amount_total':0.0,'slabs':[], 'conditional_ekyc_total':None,
                'conditional_ovd_total':None,'verified_expected_commission':None,
                'note':f'Initial Deposit scenario could not be calculated: {type(exc).__name__}'}


def _count_control_masks(frame: pd.DataFrame):
    """Return consistent count-control masks for CSP + transaction-type groups.

    Missing BC base/variance remains in the denominator and is not a match.
    Only explicitly count-measured groups are eligible for this KPI.
    """
    measurement = frame.get('measurement_type', pd.Series('UNCLASSIFIED', index=frame.index)).astype('string').str.upper().str.strip()
    successful = pd.to_numeric(frame.get('successful_transactions'), errors='coerce').fillna(0).gt(0)
    control = successful & measurement.eq('TRANSACTION_COUNT')
    report_base = pd.to_numeric(frame.get('report_base'), errors='coerce')
    variance = pd.to_numeric(frame.get('count_variance'), errors='coerce')
    matched = control & report_base.notna() & variance.notna() & variance.abs().le(1e-9)
    mismatch = control & ~matched
    missing_bc = control & report_base.isna()
    missing_variance = control & report_base.notna() & variance.isna()
    return control, matched, mismatch, missing_bc, missing_variance, report_base, variance

def _json_safe(value):
    if value is None: return None
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (bool, np.bool_)): return bool(value)
    if isinstance(value, (int, np.integer)): return int(value)
    if isinstance(value, dict): return {str(k): _json_safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [_json_safe(v) for v in value]
    try:
        if pd.isna(value): return None
    except Exception: pass
    return value.item() if hasattr(value,'item') else value


@router.get('/successful-transaction-types')
def successful_transaction_types():
    rows = _successful_transaction_type_source_summary()
    total = int(sum(int(r.get('successful_transactions') or 0) for r in rows))
    return {'source': 'Successful Transaction Sheet', 'rows': rows, 'total_successful_transactions': total, 'transaction_type_count': len(rows)}

@router.get('/summary')
def summary():
    r=load_result()
    tx=r[r.successful_transactions>0].copy()

    status_aliases={
        'Matched':'MATCH','Count Mismatch':'SOURCE_COUNT_DIFFERENCE','Unmapped Transaction Type':'UNMAPPED',
        'BC Only Activity':'BC_ONLY_ACTIVITY','Rate Master Missing':'RATE_MASTER_MISSING','Ambiguous Rate Rule':'AMBIGUOUS_RATE_RULE',
        'Missing Commission Pair':'SOURCE_COUNT_DIFFERENCE'
    }
    primary=lambda name: int((r.reconciliation_status==status_aliases.get(name,name)).sum())
    gap=lambda name: int((r.financial_gap_status==name).sum())

    expected_series=pd.to_numeric(tx.get('verified_expected_commission',tx.expected_commission),errors='coerce')
    actual_comparable=pd.to_numeric(tx.actual_comparable_commission,errors='coerce')
    actual_activity=pd.to_numeric(tx.actual_commission,errors='coerce')
    financial_gap=pd.to_numeric(tx.financial_gap,errors='coerce')

    expected=float(expected_series.sum(min_count=1)) if expected_series.notna().any() else None
    calculated_series=pd.to_numeric(tx.get('expected_commission'),errors='coerce')
    calculated_expected=float(calculated_series.sum(min_count=1)) if calculated_series.notna().any() else None
    exact_prob_mask=on_unique(tx.get('mapping_confidence',pd.Series('',index=tx.index)).astype('string'), lambda x: x.str.upper()).isin(['EXACT','PROBABLE'])
    exact_probable_expected=float(calculated_series[exact_prob_mask].sum(min_count=1)) if (exact_prob_mask & calculated_series.notna()).any() else None
    conditional_expected=float(calculated_series[~exact_prob_mask].sum(min_count=1)) if ((~exact_prob_mask) & calculated_series.notna()).any() else None
    # Canonical financial reconciliation basis: only groups whose rule is
    # settlement-approved may be compared with BC actual commission.
    # Do NOT use rate_rule_complete here because that can include provisional
    # 'Mapping Pending' rules; doing so makes the dashboard Expected figure
    # differ from the actual-comparable/variance basis and from the audit run.
    comparable_mask=(tx['settlement_rule_approved'].astype('boolean').fillna(False) & tx.expected_commission.notna() & actual_comparable.notna()) if 'settlement_rule_approved' in tx.columns else (tx.expected_commission.notna() & actual_comparable.notna())
    # Settlement-comparable expected must use the SAME approved group population
    # as actual_comparable_commission and financial_gap. Do not use the stricter
    # verified_expected_commission subset here, otherwise Expected, Actual and
    # Variance in the dashboard are calculated on different populations.
    expected_comparable=float(calculated_series[comparable_mask].sum(min_count=1)) if comparable_mask.any() else None
    expected_low_series=expected_series
    expected_high_series=expected_series
    expected_low=float(expected_low_series.sum(min_count=1)) if expected_low_series.notna().any() else None
    expected_high=float(expected_high_series.sum(min_count=1)) if expected_high_series.notna().any() else None
    geography_unresolved=int(pd.to_numeric(tx.get('geography_unresolved_transactions'),errors='coerce').fillna(0).sum()) if 'geography_unresolved_transactions' in tx.columns else 0
    actual=float(actual_comparable.sum(min_count=1)) if actual_comparable.notna().any() else None
    activity_actual=float(actual_activity.sum(min_count=1)) if actual_activity.notna().any() else 0.0
    # Financial comparison must use the SAME population on both sides.
    # `financial_gap` is populated only for settlement-comparable groups, so its
    # sum is the comparable gap, not a full-population settlement variance.
    comparable_gap_value=float(financial_gap.sum(min_count=1)) if financial_gap.notna().any() else None
    comparable_shortfall=float(financial_gap[financial_gap.gt(0)].sum(min_count=1)) if financial_gap.gt(0).any() else 0.0
    comparable_excess=float((-financial_gap[financial_gap.lt(0)]).sum(min_count=1)) if financial_gap.lt(0).any() else 0.0

    # Analytical transaction-financial control. Unlike the settlement-approved
    # figures above, this includes deterministic rules marked "Mapping to confirm"
    # when both expected and BC actual are present. It is explicitly labelled
    # provisional and never presented as a final SBI settlement variance.
    provisional_expected_series=pd.to_numeric(tx.get('expected_commission'),errors='coerce')
    provisional_actual_series=pd.to_numeric(tx['provisional_actual_commission'] if 'provisional_actual_commission' in tx.columns else pd.Series(np.nan,index=tx.index),errors='coerce')
    provisional_gap_series=pd.to_numeric(tx['provisional_financial_gap'] if 'provisional_financial_gap' in tx.columns else pd.Series(np.nan,index=tx.index),errors='coerce')
    provisional_mask=provisional_expected_series.notna() & provisional_actual_series.notna()
    provisional_expected=float(provisional_expected_series[provisional_mask].sum()) if provisional_mask.any() else None
    provisional_actual=float(provisional_actual_series[provisional_mask].sum()) if provisional_mask.any() else None
    provisional_gap=float(provisional_gap_series[provisional_mask].sum()) if provisional_mask.any() else None
    provisional_shortfall=float(provisional_gap_series[(provisional_mask) & provisional_gap_series.gt(0)].sum()) if (provisional_mask & provisional_gap_series.gt(0)).any() else 0.0
    provisional_excess=float((-provisional_gap_series[(provisional_mask) & provisional_gap_series.lt(0)]).sum()) if (provisional_mask & provisional_gap_series.lt(0)).any() else 0.0
    provisional_groups=int(provisional_mask.sum())
    provisional_pending_groups=int(((provisional_mask) & tx.get('rate_rule_pending',pd.Series(0,index=tx.index)).fillna(0).gt(0)).sum()) if 'rate_rule_pending' in tx.columns else 0

    rate_missing=primary('Rate Master Missing')
    ambiguous=primary('Ambiguous Rate Rule')
    unmapped=primary('Unmapped Transaction Type')
    # A commission is missing only when the successful CSP/type group has an
    # approved mapping but the BC row has no numeric actual commission. A missing
    # report-base/count value is a population-control issue, not missing revenue.
    missing_commission_groups=int((
        (r.successful_transactions > 0)
        & r.join_type.notna()
        & pd.to_numeric(r.actual_commission, errors='coerce').isna()
    ).sum()) if 'join_type' in r.columns and 'actual_commission' in r.columns else 0
    # `complete` is a settlement-approval control, NOT a run/calculation health flag.
    # The reconciliation engine can finish and expose comparable results even when
    # some CSP/type groups need source/master review. Those exceptions are measured
    # separately below; they must not make the dashboard look as if the calculation
    # itself failed.
    pending_mapping_groups=primary('MAPPING_PENDING')
    bc_only_transaction_groups=int(((r.successful_transactions.fillna(0).eq(0)) & r.get('measurement_type',pd.Series('UNCLASSIFIED',index=r.index)).eq('TRANSACTION_COUNT')).sum())
    settlement_rule_complete=bool(RM.exists() and rate_missing==0 and ambiguous==0 and unmapped==0 and pending_mapping_groups==0 and missing_commission_groups==0 and bc_only_transaction_groups==0)

    cm=pd.read_csv(CM,low_memory=False)
    # Account-opening/RD/STDR rule checks are not automatically count-matched to
    # Initial Deposit events. Those events do not prove account opening, KYC/OVD,
    # RD opening, or STDR sanction/area. Keep the source gap explicit.
    tx_types=set(tx.get('transaction_type',pd.Series(dtype=str)).dropna().astype(str).str.upper().str.strip())
    bc_types=set(cm.get('transaction_type',pd.Series(dtype=str)).dropna().astype(str).str.upper().str.strip())
    account_opening_bc_present=any(t.startswith('ACC OPEN') for t in bc_types)
    rd_stdr_bc_present=bool({'RD OPEN','STDR OPEN','FD OPEN'} & bc_types)
    account_opening_source_present=bool({'SB ACCOUNT OPENING','SAVING ACCOUNT OPENING','ACCOUNT OPENING','ACC OPEN'} & tx_types)
    rd_source_present=bool({'RD OPEN','OPENING OF RD ACCOUNTS'} & tx_types)
    stdr_source_present=bool({'STDR OPEN','OPENING STDR/FD','FD OPEN'} & tx_types)
    account_product_source_gap = (account_opening_bc_present and not account_opening_source_present) or (('INITIAL DEPOSIT' in tx_types) and account_opening_bc_present and not account_opening_source_present) or (rd_stdr_bc_present and not (rd_source_present or stdr_source_present))
    raw_actual=pd.to_numeric(cm.get('actual_commission'),errors='coerce')
    bc_total=float(raw_actual.sum(min_count=1)) if raw_actual.notna().any() else 0.0
    bc_only=float(pd.to_numeric(r.loc[r.successful_transactions.eq(0),'actual_commission'],errors='coerce').sum(min_count=1) or 0.0)
    unresolved_activity=float(pd.to_numeric(r.loc[(r.successful_transactions>0)&r.expected_commission.isna(),'actual_commission'],errors='coerce').sum(min_count=1) or 0.0)

    meta=load_metadata(); rm=meta.get('rate_master')
    rural_control = {'available': False, 'status': 'RURAL_CSP_SOURCE_REQUIRED', 'summary': {}, 'rows': []}
    try:
        rural_master = load_rural_master()
        # Calculated after the authoritative Success source is loaded below.
    except Exception:
        rural_master = pd.DataFrame()
    txmeta=meta.get('transactions') or {}; cmmeta=meta.get('commission') or {}
    from app.services.control_population import transaction_population_mask
    population_mask=transaction_population_mask(tx)
    population_tx=tx.loc[population_mask].copy()
    applied=int(pd.to_numeric(population_tx.get('rate_rule_applied'),errors='coerce').fillna(0).sum()) if 'rate_rule_applied' in population_tx else 0
    settlement_applied=int(pd.to_numeric(population_tx.loc[population_tx.settlement_rule_approved.astype('boolean').fillna(False),'successful_transactions'],errors='coerce').fillna(0).sum()) if 'settlement_rule_approved' in population_tx.columns else 0
    pending_rows=int(pd.to_numeric(population_tx.get('rate_rule_pending'),errors='coerce').fillna(0).sum()) if 'rate_rule_pending' in population_tx else 0
    base_tx=tx[~tx.get('is_supplemental',pd.Series(False,index=tx.index,dtype=bool)).astype('boolean').fillna(False).astype(bool)].copy()
    # Source KPIs must come from the actual uploaded Success file, not the
    # reconciliation result, because PMJJBY/PMSBY is a CSP-wise supplemental
    # control source and the 95 legacy SSS rows are deliberately replaced in the
    # reconciliation population.
    tx_source_path=Path(__file__).resolve().parents[1] / 'data' / 'transactions' / 'latest_transactions.csv'
    try:
        from app.services.transaction_processor import get_successful_transactions, load_successful_transactions
        source_success=load_successful_transactions(tx_source_path)
        source_success_amount=pd.to_numeric(source_success.get('amount'),errors='coerce').sum(min_count=1)
        eligible=int(len(source_success))
        source_transaction_amount=float(source_success_amount) if pd.notna(source_success_amount) else 0.0
    except Exception:
        eligible=int(base_tx.successful_transactions.sum())
        source_transaction_amount=float(pd.to_numeric(base_tx.transaction_amount,errors='coerce').sum(min_count=1) or 0.0)
    try:
        rural_tx_month = None
        if tx_source_path.exists():
            from app.services.transaction_processor import load_successful_transactions
            rural_tx = load_successful_transactions(tx_source_path)
            if 'transaction_date' in rural_tx.columns:
                d = parse_date_series(rural_tx['transaction_date']).dropna()
                months = d.dt.to_period('M').astype(str).unique().tolist()
                rural_tx_month = months[0] if len(months) == 1 else None
        rural_control = reconcile_rural_commission(cm, transaction_month=rural_tx_month, rural_master=load_rural_master(), txn_mapping=load_txn_mapping())
    except Exception as exc:
        rural_control = {'available': False, 'status': 'ERROR', 'message': str(exc), 'summary': {}, 'rows': []}

    from app.services.control_population import summarize_control_population
    population_counts=summarize_control_population(tx)
    reconciliation_population=population_counts['reconciliation_population_transactions']
    supplemental_rows=tx[tx.get('is_supplemental',pd.Series(False,index=tx.index,dtype=bool)).astype('boolean').fillna(False).astype(bool)].copy()
    supplemental_transactions=population_counts['supplemental_scheme_transactions']
    social_mask=supplemental_rows.transaction_type.isin(['PMJJBY','PMSBY']) if 'transaction_type' in supplemental_rows.columns else pd.Series(False,index=supplemental_rows.index)
    passbook_mask=supplemental_rows.transaction_type.eq('PASSBOOK PRINTING') if 'transaction_type' in supplemental_rows.columns else pd.Series(False,index=supplemental_rows.index)
    social_supplemental_transactions=population_counts['social_security_supplemental_transactions']
    passbook_supplemental_transactions=population_counts['passbook_printing_supplemental_transactions']
    aeps_cash_incentive_control_transactions=population_counts['aeps_cash_incentive_control_transactions']
    passbook_expected=float(pd.to_numeric(supplemental_rows.loc[passbook_mask,'expected_commission'],errors='coerce').sum(min_count=1)) if passbook_mask.any() else None
    passbook_actual=float(pd.to_numeric(supplemental_rows.loc[passbook_mask,'actual_commission'],errors='coerce').sum(min_count=1)) if passbook_mask.any() else None
    passbook_count_diff=float(pd.to_numeric(supplemental_rows.loc[passbook_mask,'passbook_count_difference'],errors='coerce').sum(min_count=1)) if passbook_mask.any() else None
    passbook_revenue_diff=float(pd.to_numeric(supplemental_rows.loc[passbook_mask,'passbook_revenue_difference'],errors='coerce').sum(min_count=1)) if passbook_mask.any() else None
    unresolved_tx=int(pd.to_numeric(population_tx.get('rate_rule_missing'),errors='coerce').fillna(0).sum()) if 'rate_rule_missing' in population_tx else 0
    ambiguous_tx=int(pd.to_numeric(population_tx.get('rate_rule_ambiguous'),errors='coerce').fillna(0).sum()) if 'rate_rule_ambiguous' in population_tx else 0

    source_controls={
        'transaction_rows_uploaded':txmeta.get('rows'),
        'transaction_raw_rows_after_header':txmeta.get('raw_rows'),
        'transaction_nonblank_rows':txmeta.get('rows'),
        'transaction_excluded_rows':(txmeta.get('validation') or {}).get('excluded_rows',0),
        'transaction_missing_date_rows':(txmeta.get('validation') or {}).get('missing_transaction_date',0),
        'transaction_duplicate_reference_rows':(txmeta.get('validation') or {}).get('duplicate_transaction_ids',0),
        'commission_rows_uploaded':cmmeta.get('rows'),
        'commission_raw_rows_after_header':cmmeta.get('raw_rows'),
        'commission_excluded_rows':(cmmeta.get('validation') or {}).get('excluded_rows',0),
        'commission_invalid_report_base_rows':(cmmeta.get('validation') or {}).get('invalid_report_base_values',0),
        'rate_master_rows_uploaded':(rm or {}).get('rows'),
        'csp_geography_rows_uploaded':(meta.get('csp_geography') or {}).get('rows'),
        'rural_csp_rows_uploaded':(meta.get('rural_csp') or {}).get('rows'),
        'rural_csp_source':(meta.get('rural_csp') or {}).get('filename'),
        'rural_csp_period':(meta.get('rural_csp') or {}).get('period'),
        'csp_geography_source':(meta.get('csp_geography') or {}).get('filename'),
        'rate_master_rules_used':(rm or {}).get('rules'),
        'transaction_period_start':txmeta.get('period_start'),
        'transaction_period_end':txmeta.get('period_end'),
        'bc_workbook_internal_controls':cmmeta.get('workbook_source_controls') or (cmmeta.get('validation') or {}).get('workbook_source_controls'),
        'social_security_supplemental_transactions':social_supplemental_transactions,
        'social_security_supplemental_source':'CSP-wise PMJJBY/PMSBY supplemental source for the current uploaded period' if social_supplemental_transactions else None,
        'passbook_printing_supplemental_transactions':passbook_supplemental_transactions,
        'passbook_printing_supplemental_source':'CSP-wise Passbook Printing supplemental source for the current uploaded period' if passbook_supplemental_transactions else None,
        'passbook_printing_expected_revenue':round(passbook_expected,2) if passbook_expected is not None else None,
        'passbook_printing_bank_revenue':round(passbook_actual,2) if passbook_actual is not None else None,
        'passbook_printing_count_difference':round(passbook_count_diff,2) if passbook_count_diff is not None else None,
        'passbook_printing_revenue_difference_bank_minus_expected':round(passbook_revenue_diff,2) if passbook_revenue_diff is not None else None,
        'passbook_printing_cap_status':'NOT_VERIFIABLE_ACCOUNT_LEVEL_SOURCE' if passbook_supplemental_transactions else None,
    }

    comparable_groups=int(((tx.successful_transactions>0) & tx.expected_commission.notna() & tx.settlement_rule_approved.astype('boolean').fillna(False)).sum()) if 'settlement_rule_approved' in tx.columns else int(((tx.successful_transactions>0) & tx.expected_commission.notna()).sum())
    # Count reconciliation is a separate control from financial reconciliation.
    # IMPORTANT: the denominator is every successful-source CSP+type group whose
    # measurement is TRANSACTION_COUNT, including groups with no numeric BC base.
    # Previously report_base.notna() excluded missing-BC groups from the KPI and
    # count_variance.fillna(0) could silently treat missing variance as a match in
    # the mismatch counter. Both behaviours inflated/unstabilized the percentage.
    count_control, count_match_mask, count_mismatch_mask, count_missing_bc_mask, count_missing_variance_mask, report_base_num, count_variance_num = _count_control_masks(tx)
    count_match=int(count_match_mask.sum())
    count_mismatch=int(count_mismatch_mask.sum())
    count_missing_bc_groups=int(count_missing_bc_mask.sum())
    count_missing_variance_groups=int(count_missing_variance_mask.sum())
    denominator=count_match+count_mismatch
    # Primary reconciliation_rate remains the homogeneous CSP+transaction-type
    # count control. Rural Commission is a separate CSP-level monthly incentive
    # control, so it is never mixed into that denominator silently. When the
    # current-period Rural CSP source is available, expose an explicit combined
    # management KPI so the dashboard can show the effect without changing the
    # meaning of the primary transaction KPI.
    rural_matched_controls = 0
    rural_control_groups = 0
    if rural_control.get('available'):
        rural_rows = rural_control.get('rows') or []
        rural_matched_controls = sum(1 for row in rural_rows if str(row.get('status')) == 'Matched')
        rural_summary = rural_control.get('summary') or {}
        rural_master_groups = int(rural_summary.get('rural_csp_count') or len(rural_rows))
        rural_unmapped_paid_controls = int(rural_summary.get('unmapped_paid_csp_count') or 0)
        # Bank-paid CSPs absent from the Rural master are distinct exceptions.
        rural_control_groups = rural_control_group_count(rural_master_groups, rural_unmapped_paid_controls)
    # DFS is a monthly financial-incentive reconciliation, not a transaction-count
    # control. Keep it separately reported so a lower monetary/CSP match rate does
    # not silently change the established transaction + Rural control KPI basis.
    dfs_matched_controls = 0
    dfs_control_groups = 0
    dfs_source_unresolved_rows = 0
    dfs_headline_matched_controls = 0
    dfs_headline_control_groups = 0
    dfs_headline_included = False
    dfs_headline_status = 'SOURCE_REQUIRED'
    dfs_control = None
    try:
        from app.api.upload import dfs_incentive_reconciliation
        dfs_control = dfs_incentive_reconciliation()
        if dfs_control.get('available') and dfs_control.get('status') == 'READY':
            dfs_rows = dfs_control.get('rows') or []
            dfs_matched_controls = sum(1 for row in dfs_rows if row.get('status') == 'MATCHED')
            dfs_control_groups = len(dfs_rows)
            dfs_summary = dfs_control.get('summary') or {}
            dfs_source_unresolved_rows = int(dfs_summary.get('unresolved_source_rows') or 0)
            (dfs_headline_matched_controls, dfs_headline_control_groups, dfs_headline_included, dfs_headline_status) = resolved_dfs_headline_controls(
                dfs_rows, dfs_source_unresolved_rows
            )
    except Exception:
        # A missing/invalid DFS source must not break the core dashboard endpoint.
        dfs_matched_controls = 0
        dfs_control_groups = 0
        dfs_source_unresolved_rows = 0
        dfs_headline_matched_controls = 0
        dfs_headline_control_groups = 0
        dfs_headline_included = False
        dfs_headline_status = 'UNAVAILABLE'
    overall_control_matched, overall_control_groups, overall_control_rate = controlled_reconciliation_kpi(
        transaction_matched=count_match,
        transaction_groups=denominator,
        rural_matched=rural_matched_controls,
        rural_groups=rural_control_groups,
    )
    # Keep the historical transaction + Rural + DFS figure available for audit
    # continuity. PMJJBY/PMSBY and Passbook have separate source populations which
    # the reconciliation engine deliberately excludes from the primary transaction
    # groups; add their READY control groups to the all-source headline exactly once.
    management_control_matched = overall_control_matched + dfs_matched_controls
    management_control_groups = overall_control_groups + dfs_control_groups
    management_control_rate = round(management_control_matched / management_control_groups * 100, 2) if management_control_groups else None
    social_security_matched_controls = 0
    social_security_control_groups = 0
    social_security_control_status = 'SOURCE_REQUIRED'
    social_security_unresolved_source_rows = 0
    try:
        ss_control = social_security()
        if ss_control.get('available') and ss_control.get('status') == 'READY':
            for scheme in ss_control.get('schemes') or []:
                matched_count = int(scheme.get('matched_csp_count') or 0)
                exceptions_count = sum(int(scheme.get(k) or 0) for k in ('bc_excess_csp_count','bc_short_csp_count','count_mismatch_csp_count'))
                social_security_matched_controls += matched_count
                social_security_control_groups += matched_count + exceptions_count
            social_security_control_status = 'READY'
            ss_quality = ss_control.get('source_data_quality') or {}
            social_security_unresolved_source_rows = int(ss_quality.get('excluded_enrollment_count') or 0)
        else:
            social_security_control_status = str(ss_control.get('status') or 'SOURCE_REQUIRED')
    except Exception:
        social_security_control_status = 'UNAVAILABLE'
    passbook_matched_controls = 0
    passbook_control_groups = 0
    passbook_control_status = 'SOURCE_REQUIRED'
    try:
        pb_control = passbook_printing()
        if pb_control.get('available') and pb_control.get('status') == 'READY':
            pb_rows = pb_control.get('rows') or []
            passbook_control_groups = len(pb_rows)
            passbook_matched_controls = sum(1 for row in pb_rows if row.get('status') == 'MATCHED_COUNTS')
            passbook_control_status = 'READY'
        else:
            passbook_control_status = str(pb_control.get('status') or 'SOURCE_REQUIRED')
    except Exception:
        passbook_control_status = 'UNAVAILABLE'
    tab_matched_controls = 0
    tab_control_groups = 0
    tab_control_status = 'SOURCE_REQUIRED'
    try:
        from app.api.upload import tab_incentive_reconciliation
        tab_control = tab_incentive_reconciliation()
        if tab_control.get('available') and tab_control.get('status') == 'READY':
            tab_rows = tab_control.get('rows') or []
            tab_matched_controls = sum(1 for row in tab_rows if str(row.get('status','')).upper() == 'MATCHED')
            tab_control_groups = len(tab_rows)
            tab_control_status = 'READY'
        else:
            tab_control_status = str(tab_control.get('status') or 'SOURCE_REQUIRED')
    except Exception:
        tab_control_status = 'UNAVAILABLE'
    # Loan Lead Generation is a distinct CSP + product + period control population.
    # Do not include provisional controls in the all-source headline: period alignment
    # alone is insufficient when sanction-limit/GST evidence is not verified.
    # Only READY, amount-verified controls may enter both numerator and denominator.
    loan_lead_matched_controls = 0
    loan_lead_control_groups = 0
    loan_lead_control_status = 'SOURCE_REQUIRED'
    loan_lead_control = None
    try:
        from app.api.upload import loan_lead_generation_reconciliation
        loan_lead_control = loan_lead_generation_reconciliation()
        if loan_lead_control.get('available'):
            loan_summary = loan_lead_control.get('summary') or {}
            loan_rows = loan_lead_control.get('match_rows') or []
            if loan_summary.get('period_aligned') and loan_summary.get('actual_payout_status') == 'VERIFIED_PERIOD':
                loan_lead_control_groups = len(loan_rows)
                loan_lead_matched_controls = sum(1 for row in loan_rows if str(row.get('status') or '').upper() in {'MATCHED', 'FULLY_MATCHED'})
                loan_lead_control_status = 'READY' if loan_lead_control.get('status') == 'READY' else 'PROVISIONAL'
            else:
                loan_lead_control_status = str(loan_lead_control.get('status') or 'PERIOD_UNVERIFIED')
    except Exception:
        loan_lead_control_status = 'UNAVAILABLE'
    # m-ATM is an independent CSP-month incentive control (SBI CM060). Include
    # it in the explicit all-source headline only when its current-period source
    # and matching BC report are available; never merge it into transaction counts.
    matm_matched_controls = 0
    matm_control_groups = 0
    matm_control_status = 'SOURCE_REQUIRED'
    matm_control = None
    try:
        from app.api.upload import matm_incentive_reconciliation
        matm_control = matm_incentive_reconciliation()
        if matm_control.get('available') and matm_control.get('status') == 'READY':
            matm_rows = matm_control.get('rows') or []
            matm_control_groups = int((matm_control.get('summary') or {}).get('control_groups') or len(matm_rows))
            matm_matched_controls = sum(1 for row in matm_rows if str(row.get('status') or '').upper() == 'MATCHED')
            matm_control_status = 'READY'
        else:
            matm_control_status = str(matm_control.get('status') or 'SOURCE_REQUIRED')
    except Exception:
        matm_control_status = 'UNAVAILABLE'

    all_source_matched, all_source_groups, all_source_rate = all_source_control_kpi(
        transaction_matched=count_match, transaction_groups=denominator,
        rural_matched=rural_matched_controls, rural_groups=rural_control_groups,
        # Exclude DFS from headline if unresolved source CSP IDs could overlap BC-only rows.
        dfs_matched=dfs_headline_matched_controls, dfs_groups=dfs_headline_control_groups,
        social_security_matched=social_security_matched_controls,
        social_security_groups=social_security_control_groups,
        passbook_matched=passbook_matched_controls, passbook_groups=passbook_control_groups,
        tab_matched=tab_matched_controls, tab_groups=tab_control_groups,
        loan_lead_matched=loan_lead_matched_controls if loan_lead_control_status == 'READY' else 0,
        loan_lead_groups=loan_lead_control_groups if loan_lead_control_status == 'READY' else 0,
        matm_matched=matm_matched_controls if matm_control_status == 'READY' else 0,
        matm_groups=matm_control_groups if matm_control_status == 'READY' else 0,
    )
    all_source_status, all_source_status_issues = all_source_kpi_status(
        transaction_groups=denominator,
        rural_ready=bool(rural_control.get('available')) and rural_control_groups > 0,
        dfs_ready=bool(dfs_headline_included) and dfs_headline_control_groups > 0,
        social_security_ready=social_security_control_status == 'READY' and social_security_control_groups > 0,
        passbook_ready=passbook_control_status == 'READY' and passbook_control_groups > 0,
        tab_ready=tab_control_status == 'READY' and tab_control_groups > 0,
        loan_lead_ready=loan_lead_control_status == 'READY' and loan_lead_control_groups > 0,
        matm_ready=matm_control_status == 'READY' and matm_control_groups > 0,
        unresolved_identity_rows=dfs_source_unresolved_rows,
        unresolved_source_rows=social_security_unresolved_source_rows,
    )
    all_source_categories = [
        *(['Transactions'] if denominator > 0 else []),
        *(['Rural Commission'] if rural_control.get('available') and rural_control_groups > 0 else []),
        *(['DFS'] if dfs_headline_included and dfs_headline_control_groups > 0 else []),
        *(['PMJJBY/PMSBY'] if social_security_control_status == 'READY' and social_security_control_groups > 0 else []),
        *(['Passbook Printing'] if passbook_control_status == 'READY' and passbook_control_groups > 0 else []),
        *(['TAB Incentive'] if tab_control_status == 'READY' and tab_control_groups > 0 else []),
        *(['Loan Lead Generation'] if loan_lead_control_status == 'READY' and loan_lead_control_groups > 0 else []),
        *(['m-ATM Cash Incentive'] if matm_control_status == 'READY' and matm_control_groups > 0 else []),
    ]
    # Rule 24 is a monthly CSP-level incentive, not a successful transaction type.
    # Include its eligible control population only in the explicitly extended
    # management KPI; never alter the primary transaction-count reconciliation rate.
    women_matched_controls = 0
    women_control_groups = 0
    women_control = None
    try:
        from app.api.upload import women_csp_incentive_reconciliation
        women_control = women_csp_incentive_reconciliation()
        if women_control.get('available') and women_control.get('status') == 'READY':
            women_rows = women_control.get('rows') or []
            # Use the Rule 24 service's own classification summary as the single
            # source of truth for matched CSP controls. Re-deriving the matched
            # count here had diverged from the service/dashboard detail and could
            # show 1/88 while the CSP-level reconciliation reported 74 matched.
            women_summary = women_control.get('summary') or {}
            women_matched_controls = int(women_summary.get('matched_in_master_csp_count') or 0)
            # Denominator contains only active/paid CSPs with a positive expected
            # incentive or a positive bank-paid amount; zero-transaction inactive
            # controls remain visible in the Rule 24 detail but do not inflate it.
            for row in women_rows:
                expected_value = pd.to_numeric(pd.Series([row.get('expected_incentive')]), errors='coerce').iloc[0]
                actual_value = pd.to_numeric(pd.Series([row.get('actual_incentive')]), errors='coerce').iloc[0]
                if (pd.notna(expected_value) and float(expected_value) > 0) or (pd.notna(actual_value) and float(actual_value) > 0):
                    women_control_groups += 1
    except Exception:
        # Missing/invalid Rule 24 evidence must not break the core dashboard endpoint.
        women_matched_controls = 0
        women_control_groups = 0
    management_plus_women_matched, management_plus_women_groups, management_plus_women_rate = controlled_reconciliation_kpi(
        transaction_matched=count_match,
        transaction_groups=denominator,
        rural_matched=rural_matched_controls,
        rural_groups=rural_control_groups,
        dfs_matched=dfs_matched_controls,
        dfs_groups=dfs_control_groups,
        women_csp_matched=women_matched_controls,
        women_csp_groups=women_control_groups,
    )
    financial_match=primary('Matched')
    # Full-population settlement readiness requires BOTH commercial coverage and
    # source-population/geography controls. A comparable-subset gap must never be
    # presented as the final settlement variance.
    settlement_ready_full = bool(settlement_rule_complete and count_mismatch == 0 and missing_commission_groups == 0 and geography_unresolved == 0)
    full_population_variance = comparable_gap_value if settlement_ready_full else None

    import json
    audit_path=Path(__file__).resolve().parents[1]/'data'/'audit'/'latest_condition_summary.json'
    audit_summary={}
    if audit_path.exists():
        try: audit_summary=json.loads(audit_path.read_text())
        except Exception: audit_summary={}
    audit_verified=float(audit_summary.get('verified_expected_commission', expected or 0.0)) if audit_summary else float(expected or 0.0)
    supplemental_verified=float(pd.to_numeric(supplemental_rows.get('verified_expected_commission'),errors='coerce').sum(min_count=1)) if not supplemental_rows.empty else 0.0
    verified_expected=float(audit_verified + supplemental_verified)
    audit_provisional_expected=float(audit_summary.get('provisional_expected_commission', 0.0)) if audit_summary else 0.0
    condition_total=int(audit_summary.get('total_transactions',eligible)) if audit_summary else eligible
    condition_ok=int(audit_summary.get('ok',0)) if audit_summary else int(applied-pending_rows)
    condition_conditional=int(audit_summary.get('conditional',0)) if audit_summary else int(pending_rows)
    condition_fail=int(audit_summary.get('condition_fail',0)) if audit_summary else 0
    condition_unmapped=int(audit_summary.get('unmapped',0)) if audit_summary else unresolved_tx
    penalty=_penalty_assessment(cm,tx,meta)
    matm_source_path=Path(__file__).resolve().parents[1]/'data'/'supplemental'/'latest_matm_incentive_counts.csv'
    matm_source=None
    if matm_source_path.exists():
        try:
            candidate=pd.read_csv(matm_source_path,dtype={'csp_id':str},low_memory=False)
            # Enforce current-period matching: do not reuse an uploaded prior-month m-ATM roster.
            date_col=next((c for c in ['transaction_date','date','txn_date'] if c in r.columns),None)
            active_periods=set()
            if date_col:
                active_periods=set(pd.to_datetime(r[date_col],errors='coerce').dropna().dt.strftime('%Y-%m').unique())
            if not active_periods:
                tx_meta=(meta.get('transactions') or {})
                start=tx_meta.get('period_start'); end=tx_meta.get('period_end') or start
                if start:
                    try:
                        active_periods=set(pd.period_range(pd.Timestamp(start),pd.Timestamp(end),freq='M').astype(str))
                    except Exception:
                        active_periods=set()
            if active_periods:
                candidate=candidate[candidate['period'].astype(str).isin(active_periods)].copy()
                matm_source=candidate if not candidate.empty else None
        except Exception:
            matm_source=None
    monthly_components=calculate_monthly_components(cm, dfs_reconciliation=dfs_control, reconciled_rows=r, matm_source=matm_source)
    verified_monthly_expected=round(float((verified_expected or 0.0) + monthly_components.get('verified_earnings',0.0)),2)
    verified_net_after_penalty=round(float(verified_monthly_expected - (penalty.get('amount') or 0.0)),2) if penalty.get('is_verified') else None
    # Final commission is the uploaded BC commission total after deducting
    # only a verified/evidenced monthly penalty. Never guess a penalty amount.
    final_commission = None
    if penalty.get('is_verified') and penalty.get('amount') is not None:
        final_commission = round(float(bc_total) - float(penalty['amount']), 2)
    bc_internal=source_controls.get('bc_workbook_internal_controls') or {}

    # ------------------------------------------------------------------
    # BC product/service commission control
    # ------------------------------------------------------------------
    # This table is sourced directly from the uploaded BC commission report.
    # It is deliberately independent of the transaction reconciliation result:
    # product/service commission is an actual-source reporting control, not an
    # SBI expected-commission calculation. Penalty is separated from product
    # commission so the operator can see gross, deductions and net distinctly.
    product_wise_commission = []
    if not cm.empty and 'transaction_type' in cm.columns and 'actual_commission' in cm.columns:
        _prod = cm.copy()
        _prod['transaction_type'] = _prod['transaction_type'].astype('string').str.strip().str.upper()
        _prod['actual_commission'] = pd.to_numeric(_prod['actual_commission'], errors='coerce')
        _prod = _prod[_prod['transaction_type'].notna() & _prod['actual_commission'].notna()].copy()
        if not _prod.empty:
            _grouped = _prod.groupby('transaction_type', dropna=False)['actual_commission'].sum().reset_index()
            _grouped['is_penalty'] = _grouped['transaction_type'].str.contains('PENAL|FINE|DEDUCTION', regex=True, na=False)
            _grouped = _grouped.sort_values(['is_penalty','actual_commission'], ascending=[True,False]).reset_index(drop=True)
            _gross = float(_grouped['actual_commission'].sum())
            _penalty_product = float(_grouped.loc[_grouped['is_penalty'],'actual_commission'].sum())
            _net_product = _gross - _penalty_product
            for _, _row in _grouped.iterrows():
                _value = float(_row['actual_commission'])
                product_wise_commission.append({
                    'product': str(_row['transaction_type']),
                    'commission': round(_value,2),
                    'share_pct': round((_value / _gross * 100.0),2) if _gross else 0.0,
                    'is_penalty': bool(_row['is_penalty']),
                })
            product_commission_total = round(_net_product,2)
            product_commission_gross = round(_gross,2)
            product_commission_penalty = round(_penalty_product,2)
        else:
            product_commission_total = product_commission_gross = product_commission_penalty = None
    else:
        product_commission_total = product_commission_gross = product_commission_penalty = None

    # ------------------------------------------------------------------
    # Source-count reconciliation control
    # ------------------------------------------------------------------
    # This is deliberately a source control, not a forced-balancing routine.
    # Use the SAME denominator as the primary dashboard count KPI: all successful
    # source CSP+type groups with TRANSACTION_COUNT measurement. Missing BC base
    # or missing variance is an exception, not a reason to remove the group.
    _cc, exact_mask, mismatch_mask, missing_bc_mask, missing_var_mask, _rb, _cv = _count_control_masks(r)
    count_rows = r[_cc].copy()
    count_rows['report_base_num'] = _rb.loc[count_rows.index]
    count_rows['count_variance_num'] = _cv.loc[count_rows.index]
    count_rows['is_exact_count_match'] = exact_mask.loc[count_rows.index]
    exact_count_rows = count_rows[count_rows['is_exact_count_match']].copy()
    mismatch_count_rows = count_rows[~count_rows['is_exact_count_match']].copy()
    comparable_count_rows = count_rows.copy()  # full successful-source control population
    missing_bc_rows = count_rows[count_rows['report_base_num'].isna()]

    # Aggregate the same CSP+type control to transaction-type level so the
    # operator can immediately see which source populations are driving the
    # mismatch. This does not change the underlying reconciliation result.
    type_control = []
    if not count_rows.empty:
        g = count_rows.groupby('transaction_type', dropna=False).agg(
            successful_transactions=('successful_transactions','sum'),
            bc_report_transactions=('report_base_num', lambda x: x.sum(min_count=1)),
            comparable_groups=('report_base_num', lambda x: int(x.notna().sum())),
            mismatch_groups=('count_variance_num', lambda x: int(x.notna().sum() and (x.fillna(0).abs() > 1e-9).sum())),
            missing_bc_groups=('report_base_num', lambda x: int(x.isna().sum())),
        ).reset_index()
        g['count_difference']=g['successful_transactions']-g['bc_report_transactions']
        for _, row in g.sort_values('count_difference', key=lambda x: x.abs(), ascending=False).head(15).iterrows():
            type_control.append({
                'transaction_type': None if pd.isna(row['transaction_type']) else str(row['transaction_type']),
                'successful_transactions': int(row['successful_transactions']),
                'bc_report_transactions': None if pd.isna(row['bc_report_transactions']) else round(float(row['bc_report_transactions']),2),
                'count_difference': None if pd.isna(row['count_difference']) else round(float(row['count_difference']),2),
                'comparable_groups': int(row['comparable_groups']),
                'mismatch_groups': int(row['mismatch_groups']),
                'missing_bc_groups': int(row['missing_bc_groups'])
            })

    # CSP population control: the BC report can contain CSPs that have no row in
    # the successful-transaction source. Those are BC-only source population,
    # not transaction-count mismatches and must not be silently treated as zero.
    success_csps=set(tx['csp_id'].astype('string').str.strip().str.upper().dropna().tolist()) if 'csp_id' in tx.columns else set()
    bc_csps=set(cm['csp_id'].astype('string').str.strip().str.upper().dropna().tolist()) if 'csp_id' in cm.columns else set()
    source_count_control={
        'basis':'CSP + transaction type; successful source count vs BC rows explicitly classified as TRANSACTION_COUNT',
        'successful_source_csps':len(success_csps),
        'bc_source_csps':len(bc_csps),
        'overlapping_csps':len(success_csps & bc_csps),
        'bc_only_csps':len(bc_csps-success_csps),
        'count_control_groups':int(len(count_rows)),
        'count_comparable_groups':int(len(comparable_count_rows)),
        'count_matched_groups':int(len(exact_count_rows)),
        'count_mismatch_groups':int(len(mismatch_count_rows)),
        'missing_bc_groups':int(len(missing_bc_rows)),
        'missing_count_variance_groups':int((count_rows['report_base_num'].notna() & count_rows['count_variance_num'].isna()).sum()),
        'unmapped_success_groups':int(unmapped),
        'bc_only_activity_groups':int(primary('BC Only Activity')),
        'match_rate_pct':round(len(exact_count_rows)/len(count_rows)*100,2) if len(count_rows) else 0.0,
        'type_breakdown':type_control,
        'interpretation':'Only BC rows classified as TRANSACTION_COUNT are count-comparable. Average balance, incentive, reimbursement, penalty and unclassified BC categories are not treated as transaction counts. The dashboard reports source differences; it never forces BC counts to equal successful counts.'
    }

    initial_deposit_control = _initial_deposit_conditional_summary()
    payload={
      'initial_deposit_conditional_calculation': initial_deposit_control,
      'successful_transactions':eligible,
      'eligible_transactions':eligible,
      'reconciliation_population_transactions':reconciliation_population,
      'supplemental_scheme_transactions':supplemental_transactions,
      'aeps_cash_incentive_control_transactions':aeps_cash_incentive_control_transactions,
      'transaction_amount':round(source_transaction_amount,2),
      'expected_commission':round(verified_expected,2) if verified_expected is not None else None,
      'verified_expected_commission':round(verified_expected,2),
      'calculated_expected_commission':round(calculated_expected,2) if calculated_expected is not None else None,
      'exact_probable_expected_commission':round(exact_probable_expected,2) if exact_probable_expected is not None else None,
      'conditional_expected_commission':round(conditional_expected,2) if conditional_expected is not None else None,
      'verified_monthly_earnings_components':round(float(monthly_components.get('verified_earnings',0.0)),2),
      'conditional_monthly_earnings_components':round(float(monthly_components.get('conditional_earnings',0.0)),2),
      'verified_monthly_expected_commission':verified_monthly_expected,
      'verified_monthly_net_after_penalty':verified_net_after_penalty,
      'monthly_expected_components':monthly_components.get('components',[]),
      'monthly_required_evidence':monthly_components.get('required_evidence',[]),
      'provisional_expected_commission':round(audit_provisional_expected,2),
      'condition_audit':{'total_transactions':condition_total,'ok':condition_ok,'conditional':condition_conditional,'condition_fail':condition_fail,'unmapped':condition_unmapped,'coverage_pct':round(condition_ok/condition_total*100,2) if condition_total else 0},
      'expected_commission_covered':round(expected,2) if expected is not None else None,
      'expected_commission_comparable':round(expected_comparable,2) if expected_comparable is not None else None,
      'expected_commission_scenario_low':round(expected_low,2) if expected_low is not None else None,
      'expected_commission_scenario_high':round(expected_high,2) if expected_high is not None else None,
      'geography_unresolved_transactions':geography_unresolved,
      'expected_commission_complete':bool(expected is not None and settlement_rule_complete),
      'reconciliation_calculation_complete':bool(RM.exists()),
      'settlement_ready':settlement_ready_full,
      'settlement_block_reasons':[x for x in [
          'Rate/master exceptions' if (rate_missing or ambiguous or unmapped or pending_mapping_groups) else None,
          'Missing BC commission groups' if missing_commission_groups else None,
          'Source count mismatches' if count_mismatch else None,
          'BC-only transaction activity' if bc_only_transaction_groups else None,
          'CSP geography scenarios' if geography_unresolved else None
      ] if x],
      'expected_commission_uncovered_transactions':unresolved_tx,
      'actual_commission':round(actual,2) if actual is not None else None,
      'actual_comparable_commission':round(actual,2) if actual is not None else None,
      'comparable_variance':round(full_population_variance,2) if full_population_variance is not None else (round(comparable_gap_value,2) if comparable_gap_value is not None else None),
      'actual_comparable_commission_complete':bool(actual is not None),
      'actual_transaction_activity_commission':round(activity_actual,2),
      'unresolved_actual_commission':round(unresolved_activity,2),
      'variance':round(full_population_variance,2) if full_population_variance is not None else None,
      'financial_gap':round(full_population_variance,2) if full_population_variance is not None else None,
      'financial_gap_covered':round(comparable_gap_value,2) if comparable_gap_value is not None else None,
      'financial_gap_comparable':round(comparable_gap_value,2) if comparable_gap_value is not None else None,
      'provisional_transaction_expected_commission':round(provisional_expected,2) if provisional_expected is not None else None,
      'provisional_actual_transaction_commission':round(provisional_actual,2) if provisional_actual is not None else None,
      'provisional_financial_gap':round(provisional_gap,2) if provisional_gap is not None else None,
      'provisional_shortfall_amount':round(provisional_shortfall,2),
      'provisional_excess_amount':round(provisional_excess,2),
      'provisional_financial_groups':provisional_groups,
      'provisional_mapping_pending_groups':provisional_pending_groups,
      'provisional_financial_status':(
          'Not Comparable' if provisional_gap is None else
          ('Matched' if abs(provisional_gap) <= 0.005 else
           'Shortfall' if provisional_gap > 0 else 'Excess')
      ),
      'shortfall_amount':round(comparable_shortfall,2) if comparable_gap_value is not None else None,
      'excess_amount':round(comparable_excess,2) if comparable_gap_value is not None else None,
      'expected_commission_status':('Verified' if condition_total and condition_ok==condition_total else ('Verified with exceptions' if verified_expected is not None else 'Rate Master Required')),
      'bc_report_total_commission':round(bc_total,2),
      'bc_reported_gross_commission':round(float(bc_internal.get('csp_wise_gross_commission')),2) if bc_internal.get('csp_wise_gross_commission') is not None else round(bc_total,2),
      'bc_reported_net_payable':round(float(bc_internal.get('payment_status_total_commission')),2) if bc_internal.get('payment_status_total_commission') is not None else None,
      'bc_workbook_internal_control_status':bc_internal.get('internal_control_status','NOT_APPLICABLE'),
      'bc_workbook_internal_controls':bc_internal,
      'bc_only_commission':round(bc_only,2),
      'other_bc_commission':round(bc_only,2),
      'comparable_groups':comparable_groups,
      'matched_groups':financial_match,
      'count_matched_groups':count_match,
      'count_mismatch_groups':count_mismatch,
      'financial_matched_groups':financial_match,
      'count_control_groups':denominator,
      'count_missing_bc_groups':count_missing_bc_groups,
      'count_missing_variance_groups':count_missing_variance_groups,
      'shortfall_groups':gap('Shortfall'),
      'excess_groups':gap('Excess'),
      
      'missing_commission_groups':missing_commission_groups,
      'rate_master_missing_groups':rate_missing,
      'pending_mapping_groups':pending_mapping_groups,
      'bc_only_transaction_groups':bc_only_transaction_groups,
      'ambiguous_rate_groups':ambiguous,
      'unmapped_groups':unmapped,
      'bc_only_groups':primary('BC Only Activity'),
      'reconciliation_groups_compared':int((r.successful_transactions>0).sum()),
      'financial_groups_compared':comparable_groups,
      'reconciliation_rate':round(count_match/denominator*100,2) if denominator else 0,
      'count_match_rate':round(count_match/denominator*100,2) if denominator else 0,
      'account_opening_rd_stdr_source_gap': bool(account_product_source_gap),
      'account_opening_rd_stdr_source_gap_note': ('BC report contains Account Opening/RD/STDR commission controls, but the successful transaction sheet does not contain comparable account-opening/RD/STDR event records. Initial Deposit rows are not treated as account-opening proof; these controls are excluded from the primary count-match percentage until a comparable source is uploaded.' if account_product_source_gap else None),
      'overall_controlled_reconciliation_rate': overall_control_rate,
      'overall_controlled_matched_groups': overall_control_matched,
      'overall_controlled_groups': overall_control_groups,
      'dfs_control_matched_groups': dfs_matched_controls,
      'dfs_control_groups': dfs_control_groups,
      'dfs_source_unresolved_rows': dfs_source_unresolved_rows,
      'dfs_headline_included': dfs_headline_included,
      'dfs_headline_status': dfs_headline_status,
      'dfs_headline_matched_groups': dfs_headline_matched_controls,
      'dfs_headline_control_groups': dfs_headline_control_groups,
      'management_control_matched_groups_including_dfs': management_control_matched,
      'management_control_groups_including_dfs': management_control_groups,
      'management_control_rate_including_dfs': management_control_rate,
      'all_source_control_matched_groups': all_source_matched,
      'all_source_control_groups': all_source_groups,
      'all_source_control_rate': all_source_rate,
      'all_source_control_status': all_source_status,
      'all_source_control_status_issues': all_source_status_issues,
      'all_source_control_included_categories': all_source_categories,
      'loan_lead_control_matched_groups': loan_lead_matched_controls,
      'loan_lead_control_groups': loan_lead_control_groups,
      'matm_incentive_matched_controls': matm_matched_controls,
      'matm_incentive_control_groups': matm_control_groups,
      'matm_incentive_control_status': matm_control_status,
      'loan_lead_control_status': loan_lead_control_status,
      'all_source_control_exclusions': ([('Account Opening/RD/STDR controls are not included in the primary percentage: comparable source events are missing; Initial Deposit is not treated as account-opening proof.') if account_product_source_gap else None] if account_product_source_gap else []) + ([f'Loan Lead Generation is provisional: {loan_lead_control_groups} period-aligned CSP/product control(s) included; only amount-verified MATCHED controls count in the numerator. Status: {loan_lead_control_status}.'] if loan_lead_control_groups and loan_lead_control_status != 'READY' else []) + [f'{issue}.' for issue in all_source_status_issues] + ([f'DFS headline is provisional: {dfs_headline_control_groups} identity-resolved source CSP control(s) included; {dfs_source_unresolved_rows} unresolved source row(s) and BC-only rows are excluded to prevent possible duplicate CSP counting.'] if dfs_source_unresolved_rows > 0 else []) + ([f'PMJJBY/PMSBY source quality warning: {social_security_unresolved_source_rows} enrollment row(s) with invalid/missing CSP IDs are outside the keyed control population.'] if social_security_unresolved_source_rows > 0 else []),
      'social_security_matched_controls': social_security_matched_controls,
      'social_security_control_groups': social_security_control_groups,
      'social_security_control_status': social_security_control_status,
      'social_security_unresolved_source_rows': social_security_unresolved_source_rows,
      'passbook_printing_matched_controls': passbook_matched_controls,
      'passbook_printing_control_groups': passbook_control_groups,
      'passbook_printing_control_status': passbook_control_status,
      'tab_incentive_matched_controls': tab_matched_controls,
      'tab_incentive_control_groups': tab_control_groups,
      'tab_incentive_control_status': tab_control_status,
      'women_csp_matched_controls': women_matched_controls,
      'women_csp_control_groups': women_control_groups,
      'management_control_matched_groups_including_dfs_and_women_csp': management_plus_women_matched,
      'management_control_groups_including_dfs_and_women_csp': management_plus_women_groups,
      'management_control_rate_including_dfs_and_women_csp': management_plus_women_rate,
      'women_csp_control_status': (women_control or {}).get('status', 'UNAVAILABLE'),
      'women_csp_expected_total': ((women_control or {}).get('summary') or {}).get('total_expected_for_paid_and_unpaid') if (women_control or {}).get('available') else None,
      'women_csp_actual_total': ((women_control or {}).get('summary') or {}).get('total_bank_paid') if (women_control or {}).get('available') else None,
      'women_csp_variance_total': round(float(((women_control or {}).get('summary') or {}).get('total_bank_paid', 0) or 0) - float(((women_control or {}).get('summary') or {}).get('total_expected_for_paid_and_unpaid', 0) or 0), 2) if (women_control or {}).get('available') else None,
      'rural_commission_matched_controls': rural_matched_controls,
      'rural_commission_control_groups': rural_control_groups,
      'financial_match_rate':round(financial_match/comparable_groups*100,2) if comparable_groups else 0,
      'rate_slab_configured':RM.exists(),
      'rate_master_source':rm,
      'rate_rule_applied_transactions':applied,
      'fully_comparable_transactions':int(pd.to_numeric(population_tx.loc[population_tx.settlement_rule_approved.astype('boolean').fillna(False),'successful_transactions'],errors='coerce').fillna(0).sum()) if 'settlement_rule_approved' in population_tx.columns else 0,
      'rate_rule_coverage':round(applied/eligible*100,2) if eligible else 0,
      'settlement_rule_coverage':round(settlement_applied/eligible*100,2) if eligible else 0,
      'rate_rule_pending_transactions':pending_rows,
      'ambiguous_rate_transactions':ambiguous_tx,
      'commission_rate_note':'Verified expected commission includes only transactions with one confirmed deterministic SBI rule. Mapping-to-confirm, unresolved geography, condition failures and unmapped transactions remain outside the verified monthly total; no rate is inferred from BC actuals.',
      'reconciliation_formula':'Verified Monthly Expected Transaction Commission = sum of successful transactions with one confirmed SBI rule and all required conditions satisfied. Provisional/conditional/unmapped rows are excluded from the verified total and shown as controls. Monthly incentives/reimbursements/penalties require their own evidence and are not inferred from transaction rows.',
      'control_checks':{
          'source_rows_preserved': bool((txmeta.get('rows') or 0) >= eligible and (cmmeta.get('rows') or 0) >= 0),
          'expected_transaction_coverage_complete': bool(unresolved_tx==0 and ambiguous_tx==0 and int(pd.to_numeric(population_tx.get('rate_rule_pending'),errors='coerce').fillna(0).sum())==0),
          'expected_transaction_accounted_for': bool(applied + unresolved_tx + ambiguous_tx == reconciliation_population),
          'comparable_gap_formula_balances': bool(comparable_gap_value is None or abs((expected_comparable if expected_comparable is not None else 0.0) - (actual if actual is not None else 0.0) - comparable_gap_value) < 0.005),
          'final_financial_gap_is_complete': settlement_ready_full,
          'bc_total_includes_non_comparable_categories': bool(bc_total >= (actual or 0.0))
      },
      'source_controls':source_controls,
      'penalty_assessment':penalty,
      'final_commission':final_commission,
      'bc_net_payable':final_commission,
      'rural_commission_control':rural_control,
      'rural_commission_expected':rural_control.get('summary',{}).get('expected_commission'),
      'rural_commission_paid':rural_control.get('summary',{}).get('total_bank_rural_commission'),
      'rural_commission_shortfall':rural_control.get('summary',{}).get('short_paid_amount'),
      'rural_commission_excess':rural_control.get('summary',{}).get('excess_paid_amount'),
      'rural_commission_eligible_csps':rural_control.get('summary',{}).get('eligible_csp_count'),
      'rural_commission_source_status':rural_control.get('status'),
      'product_wise_commission':product_wise_commission,
      'product_wise_commission_count':len(product_wise_commission),
      'product_commission_gross':product_commission_gross,
      'product_commission_penalty':product_commission_penalty,
      'product_commission_total_after_penalty':product_commission_total,
      'product_commission_source':'Uploaded BC / Commission source, grouped by transaction_type; penalty categories are separated from product/service commission.',
      'penalty_amount':penalty.get('amount'),
      'penalty_status':penalty.get('status'),
      'final_commission_status':('Calculated as BC Report Total Commission minus verified monthly penalty' if final_commission is not None else 'Not calculable until the monthly penalty is evidenced'),
      'final_commission_formula':'BC Report Total Commission - verified monthly penalty',
      'source_count_control':source_count_control,
      'upload_sources':meta
    }
    return _json_safe(payload)
