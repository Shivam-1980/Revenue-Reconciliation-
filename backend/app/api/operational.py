from pathlib import Path
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from app.api.reconciliation import load_result, TX, CM, RM, rec
from app.services.upload_metadata import load_metadata
from app.services.reconciliation_engine import resolve_transaction_type, build_reference_type_map, norm, ACCOUNT_OPEN_RULE
from app.services.number_parser import parse_numeric_series, parse_date_series
from app.services.commission_engine import add_expected_commission

router = APIRouter()

@router.get('/transactions')
def transaction_trace(
    search: str = '',
    csp: str = '',
    transaction_type: str = '',
    status: str = '',
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Transaction-level traceability with explicit separation of row-level expected
    commission and group-level actual/gap controls. No aggregate actual is copied into
    a transaction row as if it were a transaction-level receipt.
    """
    r = load_result()
    tx = pd.read_csv(TX, low_memory=False)
    if 'transaction_date' in tx.columns:
        tx['transaction_date'] = parse_date_series(tx['transaction_date'])
    tx['csp_id'] = tx['csp_id'].astype('string').fillna('').str.strip().str.upper()
    tx['transaction_type'] = tx['transaction_type'].astype('string').fillna('').str.strip().str.upper()
    if status:
        tx = tx[tx.get('status', pd.Series('', index=tx.index)).astype(str).str.strip().str.upper().eq(status.upper())]
    if csp:
        tx = tx[tx['csp_id'].eq(csp.strip().upper())]
    if transaction_type:
        tx = tx[tx['transaction_type'].eq(transaction_type.strip().upper())]
    if search:
        q = search.strip().upper()
        mask = (
            tx.get('transaction_id', pd.Series('', index=tx.index)).astype(str).str.upper().str.contains(q, na=False)
            | tx['csp_id'].str.contains(q, na=False)
            | tx['transaction_type'].str.contains(q, na=False)
        )
        tx = tx[mask]
    if not status:
        st = tx.get('status', pd.Series('', index=tx.index)).astype(str).str.strip().str.upper()
        tx = tx[st.isin({'SUCCESS','SUCCESSFUL','SUCCEEDED','COMPLETED'})]
    tx = tx.reset_index(drop=True)
    total = len(tx)

    cm = pd.read_csv(CM, low_memory=False)
    rules = pd.read_csv(RM, low_memory=False) if RM.exists() else None
    ref_map = build_reference_type_map(cm, rules)
    tx['amount'] = parse_numeric_series(tx.get('amount'))
    tx['_join_type'] = [resolve_transaction_type(t,a,ref_map) for t,a in zip(tx['transaction_type'],tx['amount'])]
    tx['rule_type'] = tx['_join_type']
    tx.loc[tx['transaction_type'].eq('INITIAL DEPOSIT'),'rule_type'] = ACCOUNT_OPEN_RULE
    mapped = tx[tx['_join_type'].notna()].copy()
    if RM.exists() and not mapped.empty:
        mapped,_ = add_expected_commission(mapped, rules)
        tx.loc[mapped.index,['expected_commission','commission_rule_id','rate_status']] = mapped[['expected_commission','commission_rule_id','rate_status']]
    else:
        tx['expected_commission'] = pd.NA; tx['commission_rule_id'] = pd.NA; tx['rate_status'] = 'Rate Master Missing'

    # Group-level controls are joined only for status/context. They are never exposed
    # under transaction-level actual/gap field names.
    rr = r[['csp_id','join_type','expected_commission','actual_comparable_commission','financial_gap','financial_gap_status','reconciliation_status']].copy()
    rr['join_type'] = rr['join_type'].astype('string').fillna('')
    rr = rr.rename(columns={
        'expected_commission':'group_expected_commission',
        'actual_comparable_commission':'group_actual_comparable_commission',
        'financial_gap':'group_financial_gap',
        'financial_gap_status':'group_financial_status',
        'reconciliation_status':'group_reconciliation_status'
    })
    tx = tx.merge(rr, left_on=['csp_id','_join_type'], right_on=['csp_id','join_type'], how='left')
    tx = tx.drop(columns=['_join_type','join_type'], errors='ignore')
    cols=[c for c in [
        'transaction_id','csp_id','transaction_type','transaction_date','amount','status',
        'expected_commission','commission_rule_id','rate_status',
        'group_expected_commission','group_actual_comparable_commission','group_financial_gap',
        'group_financial_status','group_reconciliation_status'
    ] if c in tx.columns]
    page=tx.iloc[offset:offset+limit][cols].copy()
    page['actual_commission_basis']='CSP + transaction type aggregate; BC source has no transaction reference'
    return {'total':total,'offset':offset,'limit':limit,'rows':rec(page),
            'control_note':'Expected commission is transaction-level where the approved rule applies. Actual commission and financial gap are group-level controls and are never presented as transaction-level received amounts.'}

@router.get('/drilldown')
def drilldown(csp: str = '', transaction_type: str = ''):
    r = load_result()
    if not csp and not transaction_type:
        raise HTTPException(400, 'Provide csp or transaction_type for drill-down.')
    x = r.copy()
    if csp: x = x[x['csp_id'].astype(str).str.upper().eq(csp.strip().upper())]
    if transaction_type: x = x[(x['transaction_type'].astype(str).str.upper().eq(transaction_type.strip().upper())) | (x['join_type'].astype(str).str.upper().eq(transaction_type.strip().upper()))]
    return rec(x.sort_values(['csp_id','transaction_type']).reset_index(drop=True))

@router.get('/run-readiness')
def run_readiness():
    meta = load_metadata()
    checks = {
        'transactions_present': bool(TX.exists() and meta.get('transactions')),
        'commission_present': bool(CM.exists() and meta.get('commission')),
        'rate_master_present': bool(RM.exists() and meta.get('rate_master')),
        'transaction_commission_same_batch': bool(meta.get('transactions') and meta.get('commission') and meta['transactions'].get('batch_id') == meta['commission'].get('batch_id')),
    }
    tx = meta.get('transactions') or {}; cm = meta.get('commission') or {}
    overlap = True
    if all([tx.get('period_start'), tx.get('period_end'), cm.get('period_start'), cm.get('period_end')]):
        overlap = not (tx['period_end'] < cm['period_start'] or cm['period_end'] < tx['period_start'])
    checks['period_overlap'] = overlap
    checks['ready'] = all(checks.values())
    return {'ready': checks['ready'], 'checks': checks, 'message': 'All required current-period sources are validated and aligned.' if checks['ready'] else 'One or more source controls are not satisfied.'}
