"""Synchronise the file workspace into the database (V62.6.207).

The deterministic reconciliation engine keeps working on its proven CSV workspace. After
every successful upload, reconciliation run or history archive, this module records the
same data in the database so other systems (the super agent) can query it:

* each normalized source file  -> one ``src_uploads`` row + its rows (only when its SHA-256 is new)
* each reconciliation run      -> ``recon_runs`` (+ ``recon_result_rows`` for the run the cache belongs to)
* each monthly history archive -> ``recon_history_snapshots``

Files that disappear (startup reset) only lose ``is_current``; stored history is never deleted.
Row data is bulk-loaded with PostgreSQL COPY (executemany on SQLite).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from sqlalchemy import and_, delete, insert, select, update

from app import crypto_store, database
from app.db_schema import (db_sync_log, recon_history_snapshots, recon_result_rows, recon_runs, src_commission_rows,
                           src_generic_rows, src_transaction_rows, src_uploads)

log = logging.getLogger("eko.db_sync")
DATA = Path(__file__).resolve().parents[1] / "data"
RUN_LOG = DATA / "audit" / "run_log.csv"
CACHE = DATA / "reconciliation_cache.csv"
CACHE_META = DATA / "reconciliation_cache_meta.json"
HISTORY_DIR = DATA / "reconciliation_history"
_sync_lock = threading.Lock()
_last = {"status": "never", "finished_at": None, "error": None, "detail": None}

FIXED_SOURCES = {
    "transactions": "transactions/latest_transactions.csv",
    "commission": "commissions/latest_commission.csv",
    "rate_master": "rate_master/latest_rate_master.csv",
    "csp_geography": "csp_geography/latest_csp_geography.csv",
    "rural_csp": "rural_csp/latest_rural_csp_master.csv",
}
# Supplemental file stem -> upload_metadata.json key (for filename/period/batch details).
META_KEYS = {
    "social_security_counts": "social_security_counts", "passbook_printing_counts": "passbook_printing_counts",
    "dfs_incentive_counts": "dfs_incentive", "women_csp_roster": "women_csp_roster", "tab_incentive_counts": "tab_incentive",
    "matm_incentive_counts": "matm_incentive", "loan_lead_generation": "loan_lead_generation",
}
TX_COLUMNS = ("transaction_id", "csp_id", "transaction_type", "amount", "transaction_date", "status")
CM_COLUMNS = ("csp_id", "transaction_type", "actual_commission", "report_base")
RESULT_COLUMNS = {"csp_id": "csp_id", "transaction_type": "transaction_type", "join_type": "join_type",
                  "successful_transactions": "successful_transactions", "transaction_amount": "transaction_amount",
                  "expected_commission": "expected_commission", "actual_comparable_commission": "actual_commission",
                  "financial_gap": "financial_gap", "reconciliation_status": "reconciliation_status",
                  "exception_flag": "exception_flag", "mismatch_reason": "mismatch_reason"}


def workspace_sources() -> dict[str, Path]:
    found = {kind: DATA / rel for kind, rel in FIXED_SOURCES.items()}
    supplemental = DATA / "supplemental"
    if supplemental.exists():
        for path in sorted(supplemental.glob("latest_*.csv")):
            found[path.stem[len("latest_"):]] = path
    return found


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s if s and s.lower() not in {"nan", "none", "null", "<na>", "nat"} else None


def _num(v):
    s = _text(v)
    if s is None:
        return None
    try:
        d = Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _int(v):
    d = _num(v)
    return int(d) if d is not None else None


def _bool(v):
    s = _text(v)
    return None if s is None else s.lower() in {"true", "1", "yes", "y"}


def _json(row: dict) -> dict:
    # Personal identifiers (account numbers, mobile, e-mail, ...) are stored masked in the database copy (last 4 only).
    return crypto_store.mask_record({k: _text(v) for k, v in row.items()})


def _clean(obj):
    """JSON-safe copy: NaN/Infinity (valid in Python's json, invalid in PostgreSQL) become null."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)


def _bulk_insert(conn, table, columns, rows):
    """COPY on PostgreSQL (fast path), executemany elsewhere. ``rows`` are tuples in column order."""
    if not rows:
        return
    if conn.dialect.name == "postgresql":
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            with cur.copy(f"COPY {table.name} ({', '.join(columns)}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row([str(v) if isinstance(v, Decimal) else json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
                                    for v in row])
    else:
        conn.execute(insert(table), [dict(zip(columns, r)) for r in rows])


def _source_rows(kind: str, upload_id: str, df: pd.DataFrame):
    records = df.to_dict("records")
    if kind == "transactions":
        cols = ("upload_id", "row_no") + TX_COLUMNS + ("extra",)
        return src_transaction_rows, cols, [
            (upload_id, i, _text(r.get("transaction_id")), _text(r.get("csp_id")), _text(r.get("transaction_type")),
             _num(r.get("amount")), _text(r.get("transaction_date")), _text(r.get("status")),
             _json({k: v for k, v in r.items() if k not in TX_COLUMNS}))
            for i, r in enumerate(records, start=1)]
    if kind == "commission":
        cols = ("upload_id", "row_no") + CM_COLUMNS + ("extra",)
        return src_commission_rows, cols, [
            (upload_id, i, _text(r.get("csp_id")), _text(r.get("transaction_type")), _num(r.get("actual_commission")),
             _num(r.get("report_base")), _json({k: v for k, v in r.items() if k not in CM_COLUMNS}))
            for i, r in enumerate(records, start=1)]
    cols = ("upload_id", "row_no", "csp_id", "data")
    return src_generic_rows, cols, [(upload_id, i, _text(r.get("csp_id")), _json(r)) for i, r in enumerate(records, start=1)]


def _upload_meta(kind: str, metadata: dict) -> dict:
    return metadata.get(META_KEYS.get(kind, kind)) or {}


ROW_CHUNK = 20000   # rows per transaction: the database write lock is released between chunks (V62.6.213)


def sync_sources(engine, actor: str | None, metadata: dict) -> dict:
    """Record each current source file. Large files are written in chunks, each its own short transaction,
    so other requests (sign-in audit, session refresh) are never blocked for long; the upload only becomes
    ``is_current`` after all of its rows are stored, and a half-written upload is removed again on failure."""
    added, unchanged, retired = [], [], []
    present = workspace_sources()
    now = int(time.time())
    with engine.connect() as conn:
        for kind, path in present.items():
            if not path.exists() or not path.is_file():
                continue
            rel = path.relative_to(DATA).as_posix()
            sha = _sha256(path)
            existing = conn.execute(select(src_uploads.c.id).where(and_(src_uploads.c.kind == kind, src_uploads.c.sha256 == sha,
                                                                       src_uploads.c.source_file == rel))).first()
            if existing:
                upload_id = existing.id
                unchanged.append(kind)
            else:
                df = _read(path)
                upload_id = str(uuid.uuid4())
                m = _upload_meta(kind, metadata)
                conn.execute(insert(src_uploads).values(
                    id=upload_id, kind=kind, filename=m.get("filename") or path.name, sheet_name=_text(m.get("sheet_name")),
                    sha256=sha, row_count=len(df), period_start=_text(m.get("period_start")), period_end=_text(m.get("period_end")),
                    batch_id=_text(m.get("batch_id")), uploaded_at=_text(m.get("uploaded_at")), source_file=rel, synced_at=now,
                    synced_by=actor, is_current=False, meta={"columns": list(df.columns)}))
                conn.commit()
                try:
                    table, cols, rows = _source_rows(kind, upload_id, df)
                    for i in range(0, len(rows), ROW_CHUNK):
                        _bulk_insert(conn, table, cols, rows[i:i + ROW_CHUNK])
                        conn.commit()
                except BaseException:
                    conn.rollback()
                    conn.execute(delete(src_uploads).where(src_uploads.c.id == upload_id))   # rows go with it (ON DELETE CASCADE)
                    conn.commit()
                    raise
                added.append({"kind": kind, "rows": len(df)})
            conn.execute(update(src_uploads).where(and_(src_uploads.c.kind == kind, src_uploads.c.id != upload_id))
                         .values(is_current=False))
            conn.execute(update(src_uploads).where(src_uploads.c.id == upload_id).values(is_current=True))
            conn.commit()
        live = {k for k, p in present.items() if p.exists()}
        stale = conn.execute(select(src_uploads.c.kind).where(src_uploads.c.is_current.is_(True)).distinct()).scalars().all()
        for kind in stale:
            if kind not in live:
                conn.execute(update(src_uploads).where(src_uploads.c.kind == kind).values(is_current=False))
                retired.append(kind)
        conn.commit()
    return {"added": added, "unchanged": unchanged, "retired": retired}


def sync_runs(conn, actor: str | None) -> dict:
    if not RUN_LOG.exists():
        return {"runs_added": 0, "result_rows": 0}
    runs = _read(RUN_LOG).to_dict("records")
    known = set(conn.execute(select(recon_runs.c.run_id)).scalars().all())
    now, added = int(time.time()), 0
    for r in runs:
        if not r.get("run_id") or r["run_id"] in known:
            continue
        conn.execute(insert(recon_runs).values(
            run_id=r["run_id"], run_at_utc=_text(r.get("run_at_utc")), period_start=_text(r.get("transaction_period_start")),
            period_end=_text(r.get("transaction_period_end")), engine_version=None, triggered_by=actor, synced_at=now,
            transaction_sha256=_text(r.get("transaction_sha256")), commission_sha256=_text(r.get("commission_sha256")),
            rate_master_sha256=_text(r.get("rate_master_sha256")), successful_transactions=_int(r.get("successful_transactions")),
            exception_groups=_int(r.get("exception_groups")), result_rows=None, expected_commission=_num(r.get("expected_commission")),
            actual_commission=_num(r.get("actual_commission")), variance=_num(r.get("variance")),
            settlement_ready=_bool(r.get("settlement_ready")), is_current=False,
            summary={k: _text(v) for k, v in r.items()}))
        added += 1
    result_rows = _attach_results(conn)
    return {"runs_added": added, "result_rows": result_rows}


def _attach_results(conn) -> int:
    """Store the cached result rows under the run whose source hashes produced them."""
    if not CACHE.exists() or not CACHE_META.exists():
        return 0
    try:
        signature = json.loads(CACHE_META.read_text(encoding="utf-8")).get("signature") or {}
    except ValueError:
        return 0
    run = conn.execute(select(recon_runs).where(and_(recon_runs.c.transaction_sha256 == signature.get("transactions"),
                                                     recon_runs.c.commission_sha256 == signature.get("commission")))
                       .order_by(recon_runs.c.run_at_utc.desc())).first()
    if not run:
        return 0
    conn.execute(update(recon_runs).where(recon_runs.c.run_id != run.run_id).values(is_current=False))
    conn.execute(update(recon_runs).where(recon_runs.c.run_id == run.run_id)
                 .values(is_current=True, engine_version=signature.get("engine_version")))
    if run.result_rows is not None:
        return 0
    records = _read(CACHE).to_dict("records")
    cols = ("run_id", "row_no", "csp_id", "transaction_type", "join_type", "successful_transactions", "transaction_amount",
            "expected_commission", "actual_commission", "financial_gap", "reconciliation_status", "exception_flag",
            "mismatch_reason", "data")
    rows = [(run.run_id, i, _text(r.get("csp_id")), _text(r.get("transaction_type")), _text(r.get("join_type")),
             _int(r.get("successful_transactions")), _num(r.get("transaction_amount")), _num(r.get("expected_commission")),
             _num(r.get("actual_comparable_commission")), _num(r.get("financial_gap")), _text(r.get("reconciliation_status")),
             _bool(r.get("exception_flag")), _text(r.get("mismatch_reason")),
             _json({k: v for k, v in r.items() if k not in RESULT_COLUMNS}))
            for i, r in enumerate(records, start=1)]
    _bulk_insert(conn, recon_result_rows, cols, rows)
    conn.execute(update(recon_runs).where(recon_runs.c.run_id == run.run_id).values(result_rows=len(rows)))
    return len(rows)


def sync_history(conn, actor: str | None) -> dict:
    if not HISTORY_DIR.exists():
        return {"snapshots_written": 0}
    written = 0
    for path in sorted(HISTORY_DIR.glob("*.json")):
        sha = _sha256(path)
        row = conn.execute(select(recon_history_snapshots.c.sha256).where(recon_history_snapshots.c.period_key == path.stem)).first()
        if row and row.sha256 == sha:
            continue
        snapshot = _clean(json.loads(path.read_text(encoding="utf-8")))
        conn.execute(delete(recon_history_snapshots).where(recon_history_snapshots.c.period_key == path.stem))
        conn.execute(insert(recon_history_snapshots).values(period_key=path.stem, saved_at=_text(snapshot.get("saved_at")),
                                                            sha256=sha, synced_at=int(time.time()), synced_by=actor, snapshot=snapshot))
        written += 1
    return {"snapshots_written": written}


def save_month_files(actor: str | None, metadata: dict) -> dict:
    """Keep the uploaded files of the month in the database as soon as both required files are present, so a month that
    was uploaded but not yet reconciled is still there after a restart. Never raises: a failure is reported, not fatal."""
    try:
        from pathlib import Path as _P
        from app.api.reconciliation_history import _period_key
        from app.api.reconciliation import TX
        from app.services import period_store
        key, label = _period_key(metadata, _P(TX))
        return period_store.save_period_if_changed(key, label, actor)
    except Exception as exc:                               # e.g. month cannot be determined yet: nothing is saved, nothing breaks
        detail = getattr(exc, "detail", None) or f"{type(exc).__name__}: {exc}"
        return {"saved": False, "reason": str(detail)[:200]}


def sync_workspace(actor: str | None = None, trigger: str = "manual") -> dict:
    """Record the current workspace in the database. One sync at a time; each part is its own transaction."""
    from app.services.upload_metadata import load_metadata
    with _sync_lock:
        engine = database.get_engine()
        started = int(time.time())
        detail, status, error = {}, "ok", None
        try:
            metadata = load_metadata()
            detail["sources"] = sync_sources(engine, actor, metadata)
            detail["month_files"] = save_month_files(actor, metadata)
            with engine.begin() as conn:
                detail["runs"] = sync_runs(conn, actor)
            with engine.begin() as conn:
                detail["history"] = sync_history(conn, actor)
        except Exception as exc:  # recorded and surfaced via /api/database/status; never crashes the request
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            log.exception("Database sync failed")
        finished = int(time.time())
        try:
            with engine.begin() as conn:
                conn.execute(insert(db_sync_log).values(started_at=started, finished_at=finished, actor=actor, trigger=trigger,
                                                        status=status, detail={**detail, "error": error}))
        except Exception:
            log.exception("Could not write db_sync_log")
        _last.update(status=status, finished_at=finished, error=error, detail=detail)
        return {"status": status, "error": error, **detail}


def sync_in_background(actor: str | None, trigger: str) -> None:
    threading.Thread(target=sync_workspace, args=(actor, trigger), name="eko-db-sync", daemon=True).start()


def last_sync() -> dict:
    return dict(_last)
