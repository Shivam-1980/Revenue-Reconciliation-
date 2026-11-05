"""Persistent month/period history for completed reconciliations.

History is an immutable-by-period snapshot of calculated outputs, not a source
for current-period calculations. A successful rerun of the same period replaces
that period's snapshot; clearing current uploads never deletes history.
"""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from app.services.upload_metadata import load_metadata

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parents[1]
HISTORY_DIR = BASE_DIR / "data" / "reconciliation_history"
PERIOD_RE = re.compile(r"^\d{4}-\d{2}(?:_to_\d{4}-\d{2})?$")


def _period_key(meta: dict, transaction_csv: Path | None = None) -> tuple[str, str]:
    tx = meta.get("transactions") or {}
    raw_start = str(tx.get("period_start") or "")[:10]
    raw_end = str(tx.get("period_end") or "")[:10]
    # Some source layouts do not expose dates to the upload metadata parser. In
    # that case, derive the period from the normalized current transaction CSV.
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_start) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_end)) and transaction_csv and transaction_csv.is_file():
        try:
            import pandas as pd
            frame = pd.read_csv(transaction_csv, low_memory=False)
            date_col = next((c for c in frame.columns if str(c).strip().lower() in {"transaction_date", "transaction date", "txn_date", "date"}), None)
            if date_col:
                dates = pd.to_datetime(frame[date_col], errors="coerce", dayfirst=False).dropna()
                if not dates.empty:
                    raw_start, raw_end = dates.min().date().isoformat(), dates.max().date().isoformat()
        except Exception:
            pass
    start, end = raw_start[:7], raw_end[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}", end):
        # Infer only when the uploaded filename explicitly contains a month/year.
        filename = str(tx.get("filename") or "")
        match = re.search(r"(?i)(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[ _-]*(\d{2}|20\d{2})", filename)
        if match:
            months = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06","JUL":"07","AUG":"08","SEP":"09","SEPT":"09","OCT":"10","NOV":"11","DEC":"12"}
            year = int(match.group(2)); year = year if year >= 100 else 2000 + year
            start = end = f"{year:04d}-{months[match.group(1).upper()]}"
        else:
            raise HTTPException(status_code=400, detail="Cannot determine transaction month from uploaded transaction dates or filename; history was not saved to avoid mislabeling the period.")
    key = start if start == end else f"{start}_to_{end}"
    return key, start if start == end else f"{start} to {end}"


_PLAIN_TYPES = (str, int, bool, type(None))
_PLAIN = frozenset(_PLAIN_TYPES)


def _safe(value: Any):
    # Most snapshot values are plain str/int/bool/None, which are returned unchanged below;
    # short-circuit them before the type checks (snapshot archiving visits ~0.5M values).
    if type(value) in _PLAIN_TYPES: return value
    if type(value) is float: return value if value - value == 0 else None      # finite -> itself; nan/inf -> None
    # Containers of plain values dominate a snapshot: test the leaves inline instead of calling back for each one.
    if type(value) is dict: return {(k if type(k) is str else str(k)): (v if type(v) in _PLAIN else _safe(v)) for k, v in value.items()}
    if type(value) is list: return [(v if type(v) in _PLAIN else _safe(v)) for v in value]
    import math
    try:
        import pandas as pd
        import numpy as np
        if value is pd.NA or value is pd.NaT: return None
        if isinstance(value, (np.bool_,)): return bool(value)
        if isinstance(value, np.integer): return int(value)
        if isinstance(value, (np.floating, float)):
            x = float(value); return x if math.isfinite(x) else None
        if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    except ImportError: pass
    if isinstance(value, dict): return {str(k): _safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    if isinstance(value, float): return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try: return _safe(value.item())
        except Exception: pass
    return value


def _snapshot_detail_level(snapshot: dict) -> str:
    """Describe what was actually persisted; never infer missing detail."""
    if snapshot.get("legacy_audit_summary_only") or (snapshot.get("summary") or {}).get("historical_detail_level") == "summary_only":
        return "summary_only"
    required = ("csp", "transaction_types", "exceptions", "reconciliation_rows", "csp_type", "successful_transaction_types", "supplemental")
    return "full" if all(k in snapshot for k in required) else "partial"


def _load_snapshot(key: str):
    if not PERIOD_RE.fullmatch(key):
        raise HTTPException(status_code=400, detail="Invalid period key.")
    path = HISTORY_DIR / f"{key}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No saved reconciliation exists for this period.")
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise HTTPException(status_code=500, detail=f"Saved reconciliation history is unreadable: {type(exc).__name__}")


def _legacy_audit_rows() -> list[dict]:
    """Period-keyed aggregate history from audit runs created before snapshots existed."""
    try:
        from app.services.audit_service import list_runs
        runs = list_runs(200)
    except Exception:
        return []
    by_period: dict[str, dict] = {}
    month_codes = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06","JUL":"07","AUG":"08","SEP":"09","SEPT":"09","OCT":"10","NOV":"11","DEC":"12"}
    for run in runs:  # list_runs returns newest first
        start = str(run.get("transaction_period_start") or "")[:10]
        end = str(run.get("transaction_period_end") or start)[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
            sm, em = start[:7], end[:7]
            key = sm if sm == em else f"{sm}_to_{em}"
            label = sm if sm == em else f"{sm} to {em}"
        else:
            # Only infer a month from a clearly encoded source filename (e.g. SEP-26).
            filename = str(run.get("transaction_file") or "")
            match = re.search(r"(?i)(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[ _-]*(\d{2}|20\d{2})", filename)
            if not match:
                continue
            year = int(match.group(2)); year = year if year >= 100 else 2000 + year
            key = label = f"{year:04d}-{month_codes[match.group(1).upper()]}"
        if not PERIOD_RE.fullmatch(key) or key in by_period:
            continue
        by_period[key] = {
            "period_key": key, "period_label": label, "saved_at": run.get("run_at_utc"),
            "source_filenames": {"transactions": run.get("transaction_file"), "commission": run.get("commission_file"), "rate_master": run.get("rate_master_file")},
            "successful_transactions": run.get("successful_transactions"),
            "expected_commission": run.get("comparable_expected_commission", run.get("expected_commission_calculated", run.get("expected_commission"))),
            "actual_commission": run.get("actual_comparable_commission", run.get("actual_commission")),
            "variance": run.get("comparable_variance", run.get("variance")),
            "legacy_audit_summary_only": True, "_run": run,
        }
    return list(by_period.values())


def _legacy_snapshot(period_key: str):
    for item in _legacy_audit_rows():
        if item["period_key"] != period_key:
            continue
        run = item["_run"]
        summary = {
            "historical_detail_level": "summary_only",
            "historical_note": "This reconciliation predates monthly snapshots. The audit log stores aggregate totals only; CSP-wise, transaction-type and exception details were not saved for this run.",
            "successful_transactions": _safe(run.get("successful_transactions")),
            "count_control_groups": _safe(run.get("reconciliation_groups")),
            "count_matched_groups": _safe(run.get("matched_groups")),
            "expected_commission_comparable": _safe(run.get("comparable_expected_commission")),
            "verified_expected_commission": _safe(run.get("comparable_expected_commission")),
            "calculated_expected_commission": _safe(run.get("expected_commission_calculated", run.get("expected_commission"))),
            "actual_comparable_commission": _safe(run.get("actual_comparable_commission", run.get("actual_commission"))),
            "comparable_variance": _safe(run.get("comparable_variance", run.get("variance"))),
            "exception_groups": _safe(run.get("exception_groups")),
            "historical_run_id": run.get("run_id"), "historical_run_status": run.get("status"),
            "historical_period_start": run.get("transaction_period_start"), "historical_period_end": run.get("transaction_period_end"),
        }
        return {"period_key": period_key, "period_label": item["period_label"], "saved_at": item["saved_at"],
                "source_filenames": item["source_filenames"], "summary": summary, "csp": [], "transaction_types": [], "csp_type": [],
                "exceptions": [], "reconciliation_rows": [], "detail_counts": {},
                "successful_transaction_types": {}, "supplemental": {}, "legacy_audit_summary_only": True}
    return None

@router.post("/archive-current")
def archive_current_reconciliation(request: Request = None):
    """Snapshot the current completed calculation into its transaction period."""
    meta = load_metadata()
    tx = meta.get("transactions") or {}
    try:
        from app.api import dashboard, reconciliation
        # This also enforces source validation and completed reconciliation availability.
        summary = dashboard.summary()
        csp = reconciliation.csp()
        transaction_types = reconciliation.txn_type()
        csp_type = reconciliation.csp_type()
        exceptions = reconciliation.exceptions()
        successful_types = dashboard.successful_transaction_types()
        # Persist the complete normalized reconciliation result as well as UI aggregates.
        # This preserves row-level controls for historical review without ever feeding
        # historical rows back into the active-period calculation pipeline.
        from app.api.reconciliation import load_result, TX, CM, RM
        result_frame = load_result()
        reconciliation_rows = result_frame.to_dict(orient="records") if result_frame is not None else []
        supplemental = {}
        for name, fn in [
            ("social_security", reconciliation.social_security),
            ("passbook_printing", reconciliation.passbook_printing),
            ("rural_commission", reconciliation.rural_commission),
        ]:
            try: supplemental[name] = fn()
            except Exception as exc: supplemental[name] = {"available": False, "status": "NOT_AVAILABLE", "message": type(exc).__name__}
        from app.api import upload
        for name, fn in [("dfs_commission", upload.dfs_incentive_reconciliation),
                         ("women_csp_incentive", upload.women_csp_incentive_reconciliation),
                         ("tab_commission", upload.tab_incentive_reconciliation),
                         ("matm_commission", upload.matm_incentive_reconciliation),
                         ("loan_lead_commission", upload.loan_lead_generation_reconciliation)]:
            try: supplemental[name] = fn()
            except Exception as exc: supplemental[name] = {"available": False, "status": "NOT_AVAILABLE", "message": type(exc).__name__}
        from app.api.reconciliation import TX
        key, label = _period_key(meta, TX)
        snapshot = _safe({
            "period_key": key, "period_label": label,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "source_filenames": {k: (meta.get(k) or {}).get("filename") for k in ("transactions", "commission", "rate_master")},
            "source_metadata": {k: _safe(meta.get(k)) for k in ("transactions", "commission", "rate_master", "csp_geography", "rural_csp", "social_security_counts", "passbook_printing_counts", "dfs_incentive", "women_csp_roster", "tab_incentive", "matm_incentive", "loan_lead_generation")},
            "summary": {**summary, "historical_detail_level": "full"},
            "csp": csp, "transaction_types": transaction_types, "csp_type": csp_type,
            "exceptions": exceptions, "successful_transaction_types": successful_types,
            "reconciliation_rows": reconciliation_rows,
            "detail_counts": {"csp": len(csp), "transaction_types": len(transaction_types), "csp_type": len(csp_type), "exceptions": len(exceptions), "reconciliation_rows": len(reconciliation_rows)},
            "supplemental": supplemental,
        })
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        target = HISTORY_DIR / f"{key}.json"
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temp.replace(target)
        # Keep the month's uploaded source files in the database so it never has to be uploaded again.
        from app.services import period_store
        actor = getattr(getattr(request, "state", None), "principal", None) or {}
        try:
            stored = period_store.save_period(key, label, actor.get("email") or actor.get("sub"))
            sources_saved, sources_error = True, None
        except Exception as exc:
            stored, sources_saved, sources_error = None, False, f"{type(exc).__name__}: {exc}"
        return {"saved": True, "period_key": key, "period_label": label, "saved_at": snapshot["saved_at"],
                "sources_saved_to_database": sources_saved, "sources": stored, "sources_error": sources_error}
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not save completed reconciliation history: {type(exc).__name__}: {exc}")


@router.get("")
def list_reconciliation_history():
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    rows = {}
    for path in HISTORY_DIR.glob("*.json"):
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
            summary = snap.get("summary") or {}
            key = snap.get("period_key", path.stem)
            rows[key] = {"period_key": key, "period_label": snap.get("period_label", path.stem),
                         "saved_at": snap.get("saved_at"), "source_filenames": snap.get("source_filenames", {}),
                         "successful_transactions": summary.get("total_successful_transactions", summary.get("successful_transactions")),
                         "expected_commission": summary.get("expected_commission_comparable", summary.get("verified_expected_commission", summary.get("expected_commission"))),
                         "actual_commission": summary.get("actual_comparable_commission", summary.get("actual_commission")),
                         "variance": summary.get("comparable_variance", summary.get("variance")),
                         "detail_level": _snapshot_detail_level(snap),
                         "detail_counts": snap.get("detail_counts", {}),
                         "legacy_audit_summary_only": _snapshot_detail_level(snap) == "summary_only"}
        except Exception:
            continue
    # Show earlier runs in the selector even when they were saved before snapshot support.
    # Existing detailed snapshots always win; audit-only periods are explicitly labelled.
    for item in _legacy_audit_rows():
        rows.setdefault(item["period_key"], {k: v for k, v in item.items() if k != "_run"})
    try:
        from app.services import period_store
        saved = period_store.saved_periods()
    except Exception:
        saved = {}
    for key, info in saved.items():
        rows.setdefault(key, {"period_key": key, "period_label": key, "saved_at": None, "detail_level": "sources_only"})
    for key, item in rows.items():
        item["restorable"] = key in saved
        item["sources_saved_at"] = (saved.get(key) or {}).get("saved_at")
    ordered = sorted(rows.values(), key=lambda x: str(x.get("period_key", "")), reverse=True)
    return {"periods": ordered, "count": len(ordered)}


@router.post("/{period_key}/restore")
def restore_saved_month(period_key: str):
    """Put a saved month's uploaded source files back into the workspace (no re-upload needed)."""
    from app.services import period_store
    try:
        result = period_store.restore_period(period_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No saved source files for {period_key}. Only months reconciled with V62.6.211 or later can be restored.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"restored": True, **result,
            "message": f"{result['period_label']} sources restored. Run reconciliation to recalculate with the current approved SBI rules."}


@router.get("/{period_key}")
def get_reconciliation_history(period_key: str):
    try:
        return _load_snapshot(period_key)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        legacy = _legacy_snapshot(period_key)
        if legacy is not None:
            return legacy
        raise
