"""Agent data API v1 (V62.6.208), mounted at /api/agent/v1.

Built for machine clients such as the super agent: authenticate with ``X-API-Key``.
Every response is plain JSON read from the database; money is returned as exact decimal
strings; long lists use cursor pagination (``after_row`` / ``after_id`` + ``next_cursor``).

State-changing actions (upload, run, archive, clear) are the same endpoints the web app uses;
``/capabilities`` lists them so an agent can discover everything it may call. SBI commission
rules are not editable through any API: the approved rule workbook is permanent.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import and_, func, select

from app import database
from app.db_schema import (audit_events, recon_history_snapshots, recon_result_rows, recon_runs, src_commission_rows,
                           src_generic_rows, src_transaction_rows, src_uploads)
from app.platform_security import current_user
from app.services import db_sync

router = APIRouter()
MAX_LIMIT = 5000
ROW_TABLES = {"transactions": src_transaction_rows, "commission": src_commission_rows}


def _out(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value == value.to_integral() else format(value, "f").rstrip("0")
    if isinstance(value, float):
        return format(Decimal(str(value)).normalize(), "f")
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_out(v) for v in value]
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)  # JSON stored as text on SQLite
        except ValueError:
            return value
    return value


def _rows(result) -> list[dict]:
    return [_out(dict(r)) for r in result.mappings().all()]


def _conn():
    return database.get_engine().connect()


def _page(items, limit, key):
    return {"items": items, "count": len(items), "next_cursor": items[-1][key] if len(items) == limit else None}


def _upload(conn, upload_id: Optional[str], kind: str):
    q = select(src_uploads)
    q = q.where(src_uploads.c.id == upload_id) if upload_id else q.where(and_(src_uploads.c.kind == kind, src_uploads.c.is_current.is_(True)))
    row = conn.execute(q).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No {'such' if upload_id else 'current'} {kind} upload. Upload the file first or pass upload_id.")
    return row


@router.get("/capabilities")
def capabilities(request: Request):
    p = current_user(request)
    return {
        "api_version": "v1", "principal": {"id": p.get("sub"), "role": p.get("role"), "scopes": p.get("scopes"), "organization_id": p.get("org")},
        "auth": "Send header X-API-Key: <key>. Scopes: read (GET), write (actions), admin (users/keys/audit), * (everything).",
        "money_format": "Money fields are exact decimal strings, e.g. \"1000.5\"; null means not available (never zero).",
        "pagination": "Pass the returned next_cursor as after_row (or after_id); next_cursor=null means the last page.",
        "read": [
            "GET /api/agent/v1/summary", "GET /api/agent/v1/uploads?kind=&current_only=&period=",
            "GET /api/agent/v1/uploads/{upload_id}", "GET /api/agent/v1/transactions?upload_id=&csp_id=&transaction_type=&after_row=&limit=",
            "GET /api/agent/v1/commissions?upload_id=&csp_id=&after_row=&limit=", "GET /api/agent/v1/source-rows/{upload_id}?csp_id=&after_row=&limit=",
            "GET /api/agent/v1/runs?period=", "GET /api/agent/v1/runs/current", "GET /api/agent/v1/runs/{run_id}",
            "GET /api/agent/v1/runs/{run_id}/results?csp_id=&status=&exceptions_only=&after_row=&limit=",
            "GET /api/agent/v1/history", "GET /api/agent/v1/history/{period_key}", "GET /api/agent/v1/csps/{csp_id}",
            "GET /api/database/status", "Any GET route of the web app, e.g. /api/dashboard/summary, /api/reconciliation/exceptions",
        ],
        "write": [
            "POST /api/agent/v1/sync  (make the database match the workspace now)",
            "POST /api/upload/transactions  (multipart field 'file')", "POST /api/upload/commission  (multipart field 'file')",
            "POST /api/upload/<supplemental>  (see GET /openapi.json for every upload type)",
            "POST /api/reconciliation/run", "POST /api/reconciliation/history/archive-current", "POST /api/workspace/clear-current-data",
        ],
        "admin": ["GET /api/agent/v1/audit-events?after_id=&event_type=&limit=", "GET|POST /api/auth/users", "GET|POST /api/auth/api-keys",
                  "POST /api/auth/api-keys/{key_id}/revoke", "POST /api/auth/organizations"],
        "not_available": ["Editing SBI commission rules (the approved rule workbook is permanent and human-controlled)."],
        "openapi": "GET /openapi.json describes every endpoint and schema (local mode).",
    }


@router.get("/summary")
def summary():
    with _conn() as conn:
        uploads = _rows(conn.execute(select(src_uploads.c.id, src_uploads.c.kind, src_uploads.c.filename, src_uploads.c.period_start,
                                            src_uploads.c.period_end, src_uploads.c.row_count, src_uploads.c.uploaded_at)
                                     .where(src_uploads.c.is_current.is_(True)).order_by(src_uploads.c.kind)))
        run = conn.execute(select(recon_runs).where(recon_runs.c.is_current.is_(True))).mappings().first()
        periods = conn.execute(select(recon_history_snapshots.c.period_key).order_by(recon_history_snapshots.c.period_key)).scalars().all()
    return {"current_uploads": uploads, "current_run": _out({k: v for k, v in dict(run).items() if k != "summary"}) if run else None,
            "history_periods": list(periods), "last_sync": _out(db_sync.last_sync())}


@router.get("/uploads")
def list_uploads(kind: Optional[str] = None, current_only: bool = False, period: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"),
                 limit: int = Query(200, ge=1, le=1000)):
    q = select(src_uploads.c.id, src_uploads.c.kind, src_uploads.c.filename, src_uploads.c.sheet_name, src_uploads.c.sha256,
               src_uploads.c.row_count, src_uploads.c.period_start, src_uploads.c.period_end, src_uploads.c.batch_id,
               src_uploads.c.uploaded_at, src_uploads.c.synced_by, src_uploads.c.is_current)
    if kind:
        q = q.where(src_uploads.c.kind == kind)
    if current_only:
        q = q.where(src_uploads.c.is_current.is_(True))
    if period:
        q = q.where(and_(src_uploads.c.period_start <= f"{period}-31", func.coalesce(src_uploads.c.period_end, src_uploads.c.period_start) >= f"{period}-01"))
    with _conn() as conn:
        return {"items": _rows(conn.execute(q.order_by(src_uploads.c.synced_at.desc()).limit(limit)))}


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str):
    with _conn() as conn:
        return _out(dict(_upload(conn, upload_id, "source")))


def _row_page(table, upload_id, csp_id, after_row, limit, extra_filter=None):
    q = select(table).where(and_(table.c.upload_id == upload_id, table.c.row_no > after_row))
    if csp_id:
        q = q.where(table.c.csp_id == csp_id.strip().upper())
    if extra_filter is not None:
        q = q.where(extra_filter)
    with _conn() as conn:
        return _page(_rows(conn.execute(q.order_by(table.c.row_no).limit(limit))), limit, "row_no")


@router.get("/transactions")
def transactions(upload_id: Optional[str] = None, csp_id: Optional[str] = None, transaction_type: Optional[str] = None,
                 after_row: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=MAX_LIMIT)):
    with _conn() as conn:
        up = _upload(conn, upload_id, "transactions")
    if up["kind"] != "transactions":
        raise HTTPException(status_code=400, detail="upload_id is not a transactions upload; use /source-rows/{upload_id}.")
    flt = src_transaction_rows.c.transaction_type == transaction_type if transaction_type else None
    return {"upload": {"id": up["id"], "period_start": up["period_start"], "period_end": up["period_end"], "filename": up["filename"]},
            **_row_page(src_transaction_rows, up["id"], csp_id, after_row, limit, flt)}


@router.get("/commissions")
def commissions(upload_id: Optional[str] = None, csp_id: Optional[str] = None,
                after_row: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=MAX_LIMIT)):
    with _conn() as conn:
        up = _upload(conn, upload_id, "commission")
    if up["kind"] != "commission":
        raise HTTPException(status_code=400, detail="upload_id is not a commission upload; use /source-rows/{upload_id}.")
    return {"upload": {"id": up["id"], "period_start": up["period_start"], "period_end": up["period_end"], "filename": up["filename"]},
            **_row_page(src_commission_rows, up["id"], csp_id, after_row, limit)}


@router.get("/source-rows/{upload_id}")
def source_rows(upload_id: str, csp_id: Optional[str] = None, after_row: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=MAX_LIMIT)):
    """Rows of any upload (supplementals, rate master, ...); transactions/commission use their typed tables."""
    with _conn() as conn:
        up = _upload(conn, upload_id, "source")
    table = ROW_TABLES.get(up["kind"], src_generic_rows)
    return {"upload": {"id": up["id"], "kind": up["kind"], "filename": up["filename"]}, **_row_page(table, upload_id, csp_id, after_row, limit)}


@router.get("/runs")
def runs(period: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$"), limit: int = Query(100, ge=1, le=1000)):
    q = select(recon_runs).order_by(recon_runs.c.run_at_utc.desc()).limit(limit)
    if period:
        q = q.where(recon_runs.c.period_start.like(f"{period}%"))
    with _conn() as conn:
        return {"items": [{k: v for k, v in r.items() if k != "summary"} for r in _rows(conn.execute(q))]}


def _run(conn, run_id):
    q = select(recon_runs).where(recon_runs.c.is_current.is_(True)) if run_id == "current" else select(recon_runs).where(recon_runs.c.run_id == run_id)
    row = conn.execute(q).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Reconciliation run not found." if run_id != "current" else "No current reconciliation run.")
    return row


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    with _conn() as conn:
        return _out(dict(_run(conn, run_id)))


@router.get("/runs/{run_id}/results")
def run_results(run_id: str, csp_id: Optional[str] = None, status: Optional[str] = None, exceptions_only: bool = False,
                after_row: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=MAX_LIMIT)):
    with _conn() as conn:
        run = _run(conn, run_id)
        q = select(recon_result_rows).where(and_(recon_result_rows.c.run_id == run["run_id"], recon_result_rows.c.row_no > after_row))
        if csp_id:
            q = q.where(recon_result_rows.c.csp_id == csp_id.strip().upper())
        if status:
            q = q.where(recon_result_rows.c.reconciliation_status == status.strip().upper())
        if exceptions_only:
            q = q.where(recon_result_rows.c.exception_flag.is_(True))
        items = _rows(conn.execute(q.order_by(recon_result_rows.c.row_no).limit(limit)))
    return {"run_id": run["run_id"], "results_stored": run["result_rows"] is not None, **_page(items, limit, "row_no")}


@router.get("/history")
def history():
    with _conn() as conn:
        return {"items": _rows(conn.execute(select(recon_history_snapshots.c.period_key, recon_history_snapshots.c.saved_at,
                                                   recon_history_snapshots.c.synced_by).order_by(recon_history_snapshots.c.period_key)))}


@router.get("/history/{period_key}")
def history_period(period_key: str):
    with _conn() as conn:
        row = conn.execute(select(recon_history_snapshots).where(recon_history_snapshots.c.period_key == period_key)).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No archived snapshot for {period_key}.")
    return _out(dict(row))


@router.get("/csps/{csp_id}")
def csp_overview(csp_id: str):
    """Everything known about one CSP in the current workspace (current uploads and current run)."""
    cid = csp_id.strip().upper()
    with _conn() as conn:
        current = {r.kind: r.id for r in conn.execute(select(src_uploads.c.kind, src_uploads.c.id).where(src_uploads.c.is_current.is_(True)))}
        tx_by_type = []
        if "transactions" in current:
            tx_by_type = _rows(conn.execute(
                select(src_transaction_rows.c.transaction_type, func.count().label("transactions"), func.sum(src_transaction_rows.c.amount).label("amount"))
                .where(and_(src_transaction_rows.c.upload_id == current["transactions"], src_transaction_rows.c.csp_id == cid))
                .group_by(src_transaction_rows.c.transaction_type).order_by(src_transaction_rows.c.transaction_type)))
        commission = []
        if "commission" in current:
            commission = _rows(conn.execute(select(src_commission_rows).where(and_(src_commission_rows.c.upload_id == current["commission"],
                                                                                  src_commission_rows.c.csp_id == cid)).order_by(src_commission_rows.c.row_no)))
        supplemental = {}
        for kind, uid in current.items():
            if kind in ("transactions", "commission"):
                continue
            rows = _rows(conn.execute(select(src_generic_rows.c.row_no, src_generic_rows.c.data)
                                      .where(and_(src_generic_rows.c.upload_id == uid, src_generic_rows.c.csp_id == cid)).limit(200)))
            if rows:
                supplemental[kind] = rows
        run = conn.execute(select(recon_runs.c.run_id).where(recon_runs.c.is_current.is_(True))).scalar()
        results = _rows(conn.execute(select(recon_result_rows).where(and_(recon_result_rows.c.run_id == run, recon_result_rows.c.csp_id == cid))
                                     .order_by(recon_result_rows.c.row_no))) if run else []
    if not (tx_by_type or commission or supplemental or results):
        raise HTTPException(status_code=404, detail=f"CSP {cid} is not present in the current workspace.")
    return {"csp_id": cid, "transactions_by_type": tx_by_type, "bc_commission_rows": commission, "supplemental": supplemental,
            "current_run_id": run, "reconciliation_results": results}


@router.get("/audit-events")
def audit_log(after_id: int = Query(0, ge=0), event_type: Optional[str] = None, limit: int = Query(500, ge=1, le=MAX_LIMIT)):
    q = select(audit_events).where(audit_events.c.id > after_id)
    if event_type:
        q = q.where(audit_events.c.event_type == event_type)
    with _conn() as conn:
        items = _rows(conn.execute(q.order_by(audit_events.c.id).limit(limit)))
    for item in items:
        item["detail"] = _out(item.pop("detail_json", None))
    return _page(items, limit, "id")


@router.post("/sync")
def sync(request: Request):
    p = current_user(request)
    result = db_sync.sync_workspace(p.get("email") or p.get("sub"), trigger="agent")
    if result["status"] != "ok":
        raise HTTPException(status_code=500, detail=f"Database sync failed: {result['error']}")
    return _out(result)
