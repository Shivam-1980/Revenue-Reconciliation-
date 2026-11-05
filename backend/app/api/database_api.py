"""Database status and manual sync (V62.6.207). Mounted at /api/database; requires sign-in."""
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app import database
from app.db_schema import db_sync_log, recon_history_snapshots, recon_result_rows, recon_runs, src_uploads
from app.platform_security import current_user
from app.services import backup, db_sync

router = APIRouter()


@router.get("/status")
def status():
    try:
        info = database.describe()
    except Exception as exc:
        return {"connected": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}", "last_sync": db_sync.last_sync()}
    engine = database.get_engine()
    with engine.connect() as conn:
        counts = {
            "uploads": conn.execute(select(func.count()).select_from(src_uploads)).scalar(),
            "current_uploads": conn.execute(select(func.count()).select_from(src_uploads).where(src_uploads.c.is_current.is_(True))).scalar(),
            "reconciliation_runs": conn.execute(select(func.count()).select_from(recon_runs)).scalar(),
            "result_rows": conn.execute(select(func.count()).select_from(recon_result_rows)).scalar(),
            "history_snapshots": conn.execute(select(func.count()).select_from(recon_history_snapshots)).scalar(),
        }
        last = conn.execute(select(db_sync_log).order_by(db_sync_log.c.id.desc()).limit(1)).mappings().first()
    return {"connected": True, "engine": info["engine"], "server_version": info["server_version"],
            "host": info.get("host"), "database": info.get("database") if info["engine"] == "postgresql" else "local SQLite file",
            "counts": counts, "last_sync": dict(last) if last else db_sync.last_sync()}


@router.get("/backups")
def list_backups(request: Request):
    actor = current_user(request)
    if actor.get("via") != "api_key" and actor.get("role") not in {"super_admin", "org_admin"}:
        raise HTTPException(status_code=403, detail="Only administrators can see backups.")
    return {**backup.status(), "items": backup.list_backups()}


@router.get("/security-posture")
def security_posture(request: Request):
    """Checklist of the protections that are active and the steps only the owner can still do."""
    actor = current_user(request)
    if actor.get("via") != "api_key" and actor.get("role") not in {"super_admin", "org_admin"}:
        raise HTTPException(status_code=403, detail="Only administrators can see the security checklist.")
    from app.services import security_posture as posture_service
    return posture_service.posture()


@router.post("/backup")
def backup_now(request: Request):
    """Create an encrypted backup of the whole database right now (administrators)."""
    actor = current_user(request)
    if actor.get("via") != "api_key" and actor.get("role") not in {"super_admin", "org_admin"}:
        raise HTTPException(status_code=403, detail="Only administrators can create a backup.")
    try:
        return backup.create_backup(f"manual:{actor.get('email') or actor.get('sub')}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Backup failed: {type(exc).__name__}: {exc}")


@router.post("/sync")
def sync_now(request: Request):
    actor = current_user(request)
    if actor.get("via") != "api_key" and actor.get("role") not in {"super_admin", "org_admin"}:
        raise HTTPException(status_code=403, detail="Only administrators can start a manual database sync.")
    result = db_sync.sync_workspace(actor.get("email") or actor.get("sub"), trigger="manual")
    if result["status"] != "ok":
        raise HTTPException(status_code=500, detail=f"Database sync failed: {result['error']}")
    return result
