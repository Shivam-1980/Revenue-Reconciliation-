from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, uuid
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
AUDIT_DIR = BASE_DIR / 'data' / 'audit'
AUDIT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG = AUDIT_DIR / 'run_log.csv'


def sha256_file(path: Path):
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _safe(v):
    """Convert pandas/numpy values to strict JSON-safe Python values."""
    import math
    import numpy as np
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (float, np.floating)):
        return None if not math.isfinite(float(v)) else float(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return v.item() if hasattr(v, 'item') else v


def create_run_record(tx_path, cm_path, rm_path, metadata, result, status='COMPLETED'):
    run_id = 'REC-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:8].upper()
    tx_meta, cm_meta, rm_meta = metadata.get('transactions', {}), metadata.get('commission', {}), metadata.get('rate_master', {})
    total_tx = int(result.successful_transactions.sum()) if not result.empty else 0
    expected_all = pd.to_numeric(result.get('expected_commission'), errors='coerce') if 'expected_commission' in result else pd.Series(dtype=float)
    # Keep three distinct accounting bases in the audit record:
    # 1) calculated expected = all deterministic rule-covered successful rows;
    # 2) comparable expected/actual/gap = identical settlement-comparable groups;
    # 3) final variance = only available when the entire source population is controlled.
    comparable_mask = (result['settlement_rule_approved'].astype('boolean').fillna(False) & expected_all.notna()) if 'settlement_rule_approved' in result else expected_all.notna()
    expected = expected_all
    comparable_expected = expected_all[comparable_mask]
    actual = pd.to_numeric(result.get('actual_comparable_commission'), errors='coerce') if 'actual_comparable_commission' in result else pd.Series(dtype=float)
    comparable_variance = pd.to_numeric(result.get('financial_gap'), errors='coerce') if 'financial_gap' in result else pd.Series(dtype=float)
    count_variance = pd.to_numeric(result.get('count_variance', pd.Series(dtype=float)), errors='coerce')
    count_mismatch = int((count_variance.notna() & count_variance.ne(0)).sum()) if len(result) else 0
    missing_commission_groups = int(((result.get('successful_transactions', pd.Series(dtype=float)).gt(0)) & result.get('join_type', pd.Series(pd.NA, index=result.index)).notna() & result.get('report_base', pd.Series(pd.NA, index=result.index)).isna()).sum()) if len(result) else 0
    pending_groups = int((result.get('reconciliation_status', pd.Series(dtype=object)).eq('MAPPING_PENDING')).sum()) if len(result) else 0
    bc_only_transaction_groups = int(((result.get('successful_transactions', pd.Series(dtype=float)).fillna(0).eq(0)) & result.get('measurement_type', pd.Series('UNCLASSIFIED', index=result.index)).eq('TRANSACTION_COUNT')).sum()) if len(result) else 0
    geo_unresolved = int(pd.to_numeric(result.get('geography_unresolved_transactions'), errors='coerce').fillna(0).sum()) if 'geography_unresolved_transactions' in result else 0
    if 'settlement_rule_approved' in result and len(result):
        success_rows = pd.to_numeric(result.get('successful_transactions'), errors='coerce').fillna(0).gt(0)
        rate_complete = bool(result.loc[success_rows, 'settlement_rule_approved'].astype('boolean').fillna(False).all()) if success_rows.any() else False
    else:
        rate_complete = False
    settlement_ready = bool(rate_complete and count_mismatch == 0 and missing_commission_groups == 0 and pending_groups == 0 and bc_only_transaction_groups == 0 and geo_unresolved == 0)
    final_variance = comparable_variance if settlement_ready else pd.Series(dtype=float)
    matched = int((result.get('reconciliation_status') == 'MATCH').sum()) if 'reconciliation_status' in result else 0
    exceptions = int(result.get('exception_flag', pd.Series(dtype=bool)).fillna(False).sum()) if 'exception_flag' in result else 0
    record = {
        'run_id': run_id,
        'run_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': status,
        'transaction_file': tx_meta.get('filename'),
        'commission_file': cm_meta.get('filename'),
        'rate_master_file': rm_meta.get('filename'),
        'transaction_period_start': tx_meta.get('period_start'),
        'transaction_period_end': tx_meta.get('period_end'),
        'transaction_rows': tx_meta.get('rows'),
        'commission_rows': cm_meta.get('rows'),
        'rate_master_rules': rm_meta.get('rules'),
        'transaction_sha256': sha256_file(tx_path),
        'commission_sha256': sha256_file(cm_path),
        'rate_master_sha256': sha256_file(rm_path),
        'successful_transactions': total_tx,
        'reconciliation_groups': int(len(result)),
        'matched_groups': matched,
        'exception_groups': exceptions,
        'expected_commission': round(float(expected.sum()), 2) if expected.notna().any() else None,
        'expected_commission_calculated': round(float(expected_all.sum()), 2) if expected_all.notna().any() else None,
        'comparable_expected_commission': round(float(comparable_expected.sum()), 2) if comparable_expected.notna().any() else None,
        'actual_commission': round(float(actual.sum()), 2) if actual.notna().any() else None,
        'variance': round(float(final_variance.sum()), 2) if final_variance.notna().any() else None,
        'comparable_variance': round(float(comparable_variance.sum()), 2) if comparable_variance.notna().any() else None,
        'settlement_ready': settlement_ready,
        'shortfall_amount': round(float(final_variance.clip(lower=0).sum()),2) if final_variance.notna().any() else None,
        'excess_amount': round(float((-final_variance.clip(upper=0)).sum()),2) if final_variance.notna().any() else None,
        'actual_comparable_commission': round(float(actual.sum()),2) if actual.notna().any() else None,
        'unresolved_rate_groups': int((result.get('reconciliation_status') == 'RATE_MASTER_MISSING').sum()) if 'reconciliation_status' in result else 0,
        'ambiguous_rate_groups': int((result.get('reconciliation_status') == 'AMBIGUOUS_RATE_RULE').sum()) if 'reconciliation_status' in result else 0,
        'unmapped_groups': int((result.get('reconciliation_status') == 'UNMAPPED').sum()) if 'reconciliation_status' in result else 0,
        'missing_commission_groups': missing_commission_groups,
        'pending_mapping_groups': pending_groups,
        'bc_only_transaction_groups': bc_only_transaction_groups,
    }
    df = pd.DataFrame([record])
    if AUDIT_LOG.exists():
        old = pd.read_csv(AUDIT_LOG)
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(AUDIT_LOG, index=False)
    return record


def list_runs(limit=50):
    if not AUDIT_LOG.exists():
        return []
    df = pd.read_csv(AUDIT_LOG).tail(max(1, min(int(limit), 200)))
    rows = df.iloc[::-1].to_dict(orient='records')
    return [{k: _safe(v) for k, v in row.items()} for row in rows]
