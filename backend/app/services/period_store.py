"""Saved reconciliation months in the database (V62.6.211).

After a successful reconciliation the month's uploaded source files (transactions, BC commission and
every supplemental, with their upload metadata) are stored byte-for-byte as one compressed bundle.
Restoring a month writes exactly those files back into the workspace, so the month can be viewed or
re-run without uploading anything again. Re-saving a month replaces its bundle.

Not included (deliberately): the permanent SBI rule master (rate_master/, expected_commission_rule/) –
a restored month is recalculated with the current approved rules – and generated outputs (caches,
audit logs, history snapshots), which are rebuilt by running reconciliation.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import time
import zipfile
from pathlib import Path

from sqlalchemy import delete, insert, select

from app import crypto_store, database
from app.db_schema import period_workspaces

DATA = Path(__file__).resolve().parents[1] / "data"
SOURCE_DIRS = ("transactions", "commissions", "supplemental", "csp_geography", "rural_csp")
META_FILE = "upload_metadata.json"
PERMANENT_META_KEYS = ("rate_master", "expected_commission_rule")


def _source_files():
    for sub in SOURCE_DIRS:
        folder = DATA / sub
        if folder.exists():
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
                    yield path


def save_period(period_key: str, period_label: str | None = None, saved_by: str | None = None) -> dict:
    files = list(_source_files())
    if not any(p.parent.name == "transactions" for p in files) or not any(p.parent.name == "commissions" for p in files):
        raise ValueError("The transaction and BC commission sources must be present to save a month.")
    buf = io.BytesIO()
    manifest = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:       # level 1: ~4x faster, size within a few percent
        for path in files:
            rel = path.relative_to(DATA).as_posix()
            data = path.read_bytes()
            already_compressed = rel.lower().endswith((".xlsx", ".zip"))                  # re-deflating an xlsx saves nothing and costs seconds
            zf.writestr(rel, data, compress_type=zipfile.ZIP_STORED if already_compressed else zipfile.ZIP_DEFLATED)
            manifest.append({"file": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        meta_path = DATA / META_FILE
        if meta_path.exists():
            zf.writestr(META_FILE, meta_path.read_bytes())
            manifest.append({"file": META_FILE, "bytes": meta_path.stat().st_size})
    plain = buf.getvalue()
    blob = crypto_store.encrypt_bytes(plain)           # uploaded files contain customer data: stored encrypted (AES-256-GCM)
    row = {"period_key": period_key, "period_label": period_label or period_key, "saved_at": int(time.time()), "saved_by": saved_by,
           "archive": blob, "archive_sha256": hashlib.sha256(plain).hexdigest(), "size_bytes": len(blob),
           "manifest": {"files": manifest}}
    with database.get_engine().begin() as conn:
        conn.execute(delete(period_workspaces).where(period_workspaces.c.period_key == period_key))
        conn.execute(insert(period_workspaces).values(**row))
    try:                                                 # a freshly reconciled month is worth a backup too
        from app.services import backup
        backup.schedule_backup(f"month-saved:{period_key}")
    except Exception:
        pass
    return {"period_key": period_key, "files": len(manifest), "size_bytes": len(blob)}


def encrypt_legacy_archives() -> int:
    """Encrypt saved months that were stored before encryption existed. Returns how many were converted."""
    converted = 0
    with database.get_engine().connect() as conn:
        keys = conn.execute(select(period_workspaces.c.period_key)).scalars().all()
    for key in keys:
        with database.get_engine().connect() as conn:
            blob = bytes(conn.execute(select(period_workspaces.c.archive).where(period_workspaces.c.period_key == key)).scalar())
            if crypto_store.is_encrypted(blob[:7]):
                continue
            encrypted = crypto_store.encrypt_bytes(blob)
            conn.execute(period_workspaces.update().where(period_workspaces.c.period_key == key).values(archive=encrypted, size_bytes=len(encrypted)))
            conn.commit()
            converted += 1
    return converted


def saved_periods() -> dict:
    with database.get_engine().connect() as conn:
        rows = conn.execute(select(period_workspaces.c.period_key, period_workspaces.c.period_label, period_workspaces.c.saved_at,
                                   period_workspaces.c.saved_by, period_workspaces.c.size_bytes, period_workspaces.c.manifest)).mappings().all()
    out = {}
    for r in rows:
        manifest = r["manifest"] if isinstance(r["manifest"], dict) else json.loads(r["manifest"] or "{}")
        out[r["period_key"]] = {"saved_at": r["saved_at"], "saved_by": r["saved_by"], "size_bytes": r["size_bytes"],
                                "files": [f["file"] for f in manifest.get("files", [])]}
    return out


def save_period_if_changed(period_key: str, period_label: str | None = None, saved_by: str | None = None) -> dict:
    """Store the workspace's source files for this month unless the saved bundle already holds exactly these files.

    Called after uploads, so a month whose files are uploaded but not yet reconciled still survives a restart.
    """
    files = list(_source_files())
    if not any(p.parent.name == "transactions" for p in files) or not any(p.parent.name == "commissions" for p in files):
        return {"saved": False, "reason": "transaction and BC commission sources are not both present"}
    current = {p.relative_to(DATA).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with database.get_engine().connect() as conn:
        row = conn.execute(select(period_workspaces.c.manifest).where(period_workspaces.c.period_key == period_key)).mappings().first()
    if row:
        manifest = row["manifest"] if isinstance(row["manifest"], dict) else json.loads(row["manifest"] or "{}")
        stored = {f["file"]: f.get("sha256") for f in manifest.get("files", []) if f.get("sha256")}
        if stored == current:
            return {"saved": False, "reason": "unchanged"}
    save_period(period_key, period_label, saved_by)
    return {"saved": True, "period_key": period_key, "files": len(current)}


def restore_period(period_key: str) -> dict:
    with database.get_engine().connect() as conn:
        row = conn.execute(select(period_workspaces).where(period_workspaces.c.period_key == period_key)).mappings().first()
    if not row:
        raise KeyError(period_key)
    try:
        blob = crypto_store.decrypt_bytes(bytes(row["archive"]))      # months saved before encryption was added are read as they are
    except crypto_store.DecryptionError as exc:
        raise ValueError(f"The saved month could not be decrypted ({exc}). Check that EKO_ENCRYPTION_KEY / local_secrets.json is the one used when it was saved.")
    if hashlib.sha256(blob).hexdigest() != row["archive_sha256"]:
        raise ValueError("The saved month in the database is damaged (checksum mismatch); it was not restored.")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        bad = [n for n in names if n != META_FILE and (n.startswith("/") or ".." in n.split("/") or n.split("/")[0] not in SOURCE_DIRS)]
        if bad:
            raise ValueError(f"Unexpected paths in saved month: {bad[:3]}")
        # Replace the whole current source workspace so nothing from another month is mixed in.
        for sub in SOURCE_DIRS:
            folder = DATA / sub
            if folder.exists():
                for path in folder.iterdir():
                    if path.is_file() and path.suffix.lower() in {".csv", ".json"}:
                        path.unlink()
            folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            if name == META_FILE:
                continue
            target = DATA / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
        if META_FILE in names:
            restored = json.loads(zf.read(META_FILE))
            current_path = DATA / META_FILE
            current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else {}
            for key in PERMANENT_META_KEYS:  # keep today's approved SBI rules
                restored[key] = current.get(key, restored.get(key))
            current_path.write_text(json.dumps(restored, indent=2), encoding="utf-8")
    for name in ("reconciliation_cache.csv", "reconciliation_cache_meta.json"):
        (DATA / name).unlink(missing_ok=True)
    processing = DATA / "processing" / "processing_snapshot.json"
    processing.unlink(missing_ok=True)
    return {"period_key": period_key, "period_label": row["period_label"], "files_restored": len([n for n in names if n != META_FILE])}


__all__ = ["save_period", "save_period_if_changed", "saved_periods", "restore_period", "shutil"]
