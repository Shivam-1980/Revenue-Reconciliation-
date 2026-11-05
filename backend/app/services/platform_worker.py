"""Worker for platform jobs. Tenant-safe validation only; financial jobs remain synchronous until adapters are migrated."""
from __future__ import annotations
import json, os, sqlite3, time
from pathlib import Path
from app.services import platform_jobs
from app.db_compat import USE_POSTGRES
from app.services.tenant_storage import STORAGE_ROOT as WORKSPACE_ROOT

BACKEND_DIR = Path(__file__).resolve().parents[2]

def _claim_one():
    c = platform_jobs._conn()
    try:
        if USE_POSTGRES:
            c.execute("BEGIN")
            row = c.execute("SELECT * FROM background_jobs WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        else:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM background_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            c.commit(); return None
        c.execute("UPDATE background_jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=? AND status='queued'", (int(time.time()), row['id']))
        c.commit()
        return dict(row)
    finally: c.close()

def _finish(job_id, status, result=None, error=None):
    c=platform_jobs._conn()
    try:
        c.execute("UPDATE background_jobs SET status=?, result_json=?, error=?, updated_at=? WHERE id=?",
                  (status, json.dumps(result) if result is not None else None, str(error)[:2000] if error else None, int(time.time()), job_id))
        c.commit()
    finally: c.close()

def process_one():
    job=_claim_one()
    if not job: return False
    try:
        payload=json.loads(job['payload_json'])
        org_root=(WORKSPACE_ROOT / job['organization_id']).resolve()
        org_root.mkdir(parents=True, exist_ok=True)
        def safe_path(rel):
            rel=str(rel or '').strip()
            if not rel or Path(rel).is_absolute(): raise ValueError('A relative workspace path is required.')
            candidate=(org_root / rel).resolve()
            if org_root not in candidate.parents: raise ValueError('File path escapes the organisation workspace.')
            return candidate
        if job['job_type'] == 'file_validation':
            candidate=safe_path(payload.get('relative_path'))
            if not candidate.is_file(): raise ValueError('Referenced file does not exist in the organisation workspace.')
            stat=candidate.stat()
            _finish(job['id'],'succeeded',{'valid':True,'file_name':candidate.name,'size_bytes':stat.st_size,'modified_at':int(stat.st_mtime)})
        elif job['job_type'] == 'reconciliation':
            if payload.get('source') != 'tenant_workspace': raise ValueError('Reconciliation job is not enabled for this payload; tenant_workspace source is required.')
            import pandas as pd
            from app.services.transaction_processor import get_successful_transactions
            from app.services.reconciliation_engine import reconcile_transactions
            paths=payload.get('relative_paths') or {}
            tx_path=safe_path(paths.get('transactions')); cm_path=safe_path(paths.get('commission'))
            rm_path=safe_path(paths.get('rate_master')); out_path=safe_path(paths.get('result'))
            if not tx_path.is_file() or not cm_path.is_file(): raise ValueError('Current-period transactions.csv and commission.csv are required.')
            tx=pd.read_csv(tx_path, low_memory=False); cm=pd.read_csv(cm_path, low_memory=False)
            tx=get_successful_transactions(tx)
            rules=pd.read_csv(rm_path, low_memory=False) if rm_path.is_file() else None
            result=reconcile_transactions(tx, cm, rules)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            result.to_csv(out_path, index=False)
            _finish(job['id'],'succeeded',{'organization_id':job['organization_id'],'input_transaction_rows':int(len(tx)),'commission_rows':int(len(cm)),'result_rows':int(len(result)),'result_file':str(out_path.relative_to(org_root)),'period_agnostic':True})
        elif job['job_type'] == 'report_export':
            if payload.get('source') != 'tenant_workspace': raise ValueError('Unsupported report export source.')
            import pandas as pd
            from openpyxl import Workbook
            src=safe_path(payload.get('relative_path')); dst=safe_path(payload.get('output_path'))
            if not src.is_file(): raise ValueError('Reconciliation result does not exist; run reconciliation first.')
            df=pd.read_csv(src, low_memory=False)
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Export through pandas/openpyxl, keeping each organisation's output isolated.
            df.to_excel(dst, index=False, engine='openpyxl')
            _finish(job['id'],'succeeded',{'organization_id':job['organization_id'],'rows':int(len(df)),'report_file':str(dst.relative_to(org_root))})
        else:
            raise ValueError(f"Unsupported job type: {job['job_type']}")
    except Exception as exc:
        _finish(job['id'],'failed',error=str(exc))
    return True

def run_forever(poll_seconds=1.0):
    while True:
        if not process_one(): time.sleep(max(.1, poll_seconds))

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Eko platform worker')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=float, default=1.0)
    args=parser.parse_args()
    if args.once: process_one()
    else: run_forever(args.poll_seconds)
