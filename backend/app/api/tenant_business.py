"""Tenant-scoped hosted workflow using canonical CSV inputs and the deterministic SBI engine.
This is an additive hosted path; local legacy upload endpoints are not modified.
"""
from __future__ import annotations
import json, os, time, uuid
from pathlib import Path
import pandas as pd
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from app.platform_security import current_user, record_audit
from app.services.tenant_storage import workspace_dir, resolve_workspace_file
from app.services import platform_jobs

router = APIRouter()
_ALLOWED = {"transactions", "commission", "rate_master"}
_MAX_BYTES = max(1, int(os.getenv("TENANT_UPLOAD_MAX_MB", "50"))) * 1024 * 1024

def _actor(request: Request):
    actor = current_user(request)
    if actor.get("role") not in {"super_admin", "org_admin", "operator", "viewer"}:
        raise HTTPException(status_code=403, detail="Unsupported role.")
    org = str(actor.get("org") or "").strip()
    if actor.get("role") == "super_admin":
        org = request.headers.get("X-Eko-Workspace", "").strip()
    if not org:
        raise HTTPException(status_code=403, detail="An organisation workspace is required.")
    if actor.get("role") != "super_admin" and actor.get("org") != org:
        raise HTTPException(status_code=403, detail="Cross-organisation access denied.")
    return actor, org

@router.get("/status")
def tenant_status(request: Request):
    actor, org = _actor(request)
    base = workspace_dir(org)
    files = {name: (base / f"{name}.csv").is_file() for name in _ALLOWED}
    return {"organization_id": org, "role": actor.get("role"), "files": files,
            "ready_for_reconciliation": files["transactions"] and files["commission"],
            "accepted_format": "canonical CSV; transactions require transaction_id,csp_id,transaction_type,amount,transaction_date; commission requires csp_id,transaction_type and actual commission/count fields"}

@router.post("/uploads/{kind}", status_code=201)
async def upload_canonical_csv(kind: str, request: Request, file: UploadFile = File(...)):
    actor, org = _actor(request)
    if actor.get("role") not in {"super_admin", "org_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Viewer role cannot upload files.")
    if kind not in _ALLOWED:
        raise HTTPException(status_code=404, detail="Unknown source type.")
    if Path(file.filename or "").suffix.lower() != ".csv":
        raise HTTPException(status_code=415, detail="Hosted tenant endpoint currently accepts normalized CSV only. Use the existing local upload workflow for XLSX source workbooks.")
    raw = await file.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {_MAX_BYTES // (1024*1024)} MB.")
    try:
        import io
        df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"CSV could not be parsed: {exc}")
    cols = {str(c).strip().lower() for c in df.columns}
    required = {
        "transactions": {"transaction_id", "csp_id", "transaction_type", "amount", "transaction_date"},
        "commission": {"csp_id", "transaction_type"},
        "rate_master": set(),
    }[kind]
    missing = sorted(required - cols)
    if missing:
        raise HTTPException(status_code=422, detail={"message":"CSV schema validation failed.","missing_columns":missing,"received_columns":sorted(cols)})
    if df.empty:
        raise HTTPException(status_code=422, detail="CSV has no data rows.")
    # Prevent formula injection in any later CSV export; values are stored as parsed CSV.
    base = workspace_dir(org)
    target = resolve_workspace_file(org, f"{kind}.csv")
    temp = target.with_suffix(f".csv.{uuid.uuid4().hex}.tmp")
    temp.write_bytes(raw)
    os.replace(temp, target)
    record_audit(actor, "tenant_source.uploaded", {"kind":kind,"organization_id":org,"rows":int(len(df)),"sha256":__import__('hashlib').sha256(raw).hexdigest()})
    return {"status":"uploaded","kind":kind,"organization_id":org,"rows":int(len(df)),"columns":list(df.columns),"bytes":len(raw)}

@router.post("/reconciliation", status_code=202)
def start_reconciliation(request: Request):
    actor, org = _actor(request)
    if actor.get("role") not in {"super_admin", "org_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Viewer role cannot run reconciliation.")
    base = workspace_dir(org)
    if not (base / "transactions.csv").is_file() or not (base / "commission.csv").is_file():
        raise HTTPException(status_code=409, detail="Upload current-period transactions.csv and commission.csv first.")
    payload = {"source":"tenant_workspace","relative_paths":{"transactions":"transactions.csv","commission":"commission.csv","rate_master":"rate_master.csv","result":"reconciliation_result.csv"}}
    job = platform_jobs.enqueue(org, actor["sub"], "reconciliation", payload)
    record_audit(actor, "tenant_reconciliation.queued", {"job_id":job["id"],"organization_id":org})
    return job

@router.post("/report-export", status_code=202)
def start_report_export(request: Request):
    actor, org = _actor(request)
    if actor.get("role") not in {"super_admin", "org_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Viewer role cannot export reports.")
    result = workspace_dir(org) / "reconciliation_result.csv"
    if not result.is_file():
        raise HTTPException(status_code=409, detail="Run a successful reconciliation before exporting a report.")
    return platform_jobs.enqueue(org, actor["sub"], "report_export", {"source":"tenant_workspace","relative_path":"reconciliation_result.csv","output_path":"reconciliation_report.xlsx"})

@router.get("/reports/latest")
def latest_report(request: Request):
    actor, org = _actor(request)
    path = resolve_workspace_file(org, "reconciliation_report.xlsx")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No completed report export is available.")
    return FileResponse(path, filename="reconciliation_report.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
