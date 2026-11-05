from fastapi import APIRouter, HTTPException
from app.services.audit_service import list_runs, AUDIT_LOG
from app.api.reconciliation import load_result
from app.services.upload_metadata import load_metadata

router = APIRouter()

@router.get('/runs')
def runs(limit: int = 50):
    return {'runs': list_runs(limit)}

@router.get('/latest')
def latest():
    rows = list_runs(1)
    if not rows:
        raise HTTPException(404, 'No reconciliation run has been recorded yet. Click Run Reconciliation after uploading the three source files.')
    return rows[0]

@router.get('/controls')
def controls():
    r = load_result()
    meta = load_metadata()
    status_counts = r['reconciliation_status'].value_counts().to_dict() if 'reconciliation_status' in r else {}
    missing_commission_groups=int(((r.successful_transactions>0) & r.join_type.notna() & r.actual_commission.isna()).sum()) if 'join_type' in r.columns and 'actual_commission' in r.columns else 0
    return {
        'period_start': meta.get('transactions', {}).get('period_start'),
        'period_end': meta.get('transactions', {}).get('period_end'),
        'sources': meta,
        'controls': {
            'successful_transaction_count': int(r.successful_transactions.sum()),
            'reconciliation_groups': int(len(r)),
            'matched_groups': int(status_counts.get('MATCH', 0)),
            'count_mismatch_groups': int(status_counts.get('SOURCE_COUNT_DIFFERENCE', 0)),
            'shortfall_groups': int(status_counts.get('Shortfall', 0)),
            'excess_groups': int(status_counts.get('Excess', 0)),
            'missing_commission_groups': missing_commission_groups,
            'bc_only_groups': int(status_counts.get('BC_ONLY_ACTIVITY', 0)),
            'rate_master_missing_groups': int(status_counts.get('RATE_MASTER_MISSING', 0)),
            'ambiguous_rate_groups': int(status_counts.get('AMBIGUOUS_RATE_RULE', 0)),
            'unmapped_transaction_groups': int(status_counts.get('UNMAPPED', 0)),
        },
        'audit_log_file_present': AUDIT_LOG.exists(),
        'message': 'Financial calculations are deterministic. AI does not calculate or alter commission values.'
    }
