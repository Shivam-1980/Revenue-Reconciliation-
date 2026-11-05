"""Encrypted database backups (V62.6.214), identical for SQLite and PostgreSQL.

A backup is one file ``eko_backup_YYYYmmdd_HHMMSS.ekobak`` = a zip (manifest + one JSON-lines file per table)
encrypted with AES-256-GCM (see crypto_store). It contains everything in the database: users, uploaded rows,
reconciliation runs and results, saved months (their uploaded source files), history and the audit log.

* create      -> written next to the data (or EKO_BACKUP_DIR, e.g. a OneDrive/external-drive folder); newest EKO_BACKUP_KEEP kept
* verify      -> decrypts and checks every table's row count against the manifest, without touching the database
* restore     -> loads a backup into an EMPTY database (refuses otherwise unless force=True)
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, insert, select, text

from app import crypto_store, database
from app.db_schema import metadata

log = logging.getLogger("eko.backup")
BACKEND = Path(__file__).resolve().parents[2]
FORMAT = 1
CHUNK = 5000
_lock = threading.Lock()
_last = {"status": "never", "file": None, "at": None, "error": None}


def backup_dir() -> Path:
    path = Path(os.getenv("EKO_BACKUP_DIR", str(BACKEND / "data" / "backups")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def keep_count() -> int:
    return max(1, int(os.getenv("EKO_BACKUP_KEEP", "14")))


def _enc(value):
    if isinstance(value, Decimal):
        return {"__eko_type": "dec", "v": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__eko_type": "b64", "v": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _dec(value):
    if isinstance(value, dict) and value.get("__eko_type") == "dec":
        return Decimal(value["v"])
    if isinstance(value, dict) and value.get("__eko_type") == "b64":
        return base64.b64decode(value["v"])
    return value


def create_backup(label: str = "manual") -> dict:
    """Write one encrypted backup; returns its description. Never leaves a half-written file behind."""
    with _lock:
        engine = database.get_engine()
        started = time.time()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final = backup_dir() / f"eko_backup_{stamp}.ekobak"
        counts = {}
        fd, tmp_zip = tempfile.mkstemp(suffix=".zip"); os.close(fd)
        try:
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
                for table in metadata.sorted_tables:
                    n = 0
                    with zf.open(f"tables/{table.name}.jsonl", "w", force_zip64=True) as out, engine.connect() as conn:
                        result = conn.execution_options(stream_results=True).execute(select(table))
                        while True:
                            rows = result.mappings().fetchmany(CHUNK)
                            if not rows:
                                break
                            out.write(("\n".join(json.dumps({k: _enc(v) for k, v in r.items()}, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n").encode("utf-8"))
                            n += len(rows)
                    counts[table.name] = n
                manifest = {"format": FORMAT, "created_utc": datetime.now(timezone.utc).isoformat(), "engine": engine.dialect.name,
                            "label": label, "tables": counts, "columns": {t.name: [c.name for c in t.columns] for t in metadata.sorted_tables}}
                zf.writestr("manifest.json", json.dumps(manifest, indent=1))
            tmp_final = final.with_suffix(".part")
            with open(tmp_zip, "rb") as src, open(tmp_final, "wb") as dst:
                crypto_store.encrypt_stream(src, dst)
            os.replace(tmp_final, final)
        finally:
            for leftover in (tmp_zip, str(final.with_suffix(".part"))):
                try: os.unlink(leftover)
                except OSError: pass
        _prune()
        info = {"file": final.name, "path": str(final), "size_bytes": final.stat().st_size, "rows": sum(counts.values()),
                "tables": counts, "seconds": round(time.time() - started, 1), "label": label}
        _last.update(status="ok", file=final.name, at=int(time.time()), error=None)
        log.warning("Backup created: %s (%d rows, %.1f MB, %.0fs)", final.name, info["rows"], info["size_bytes"] / 1e6, info["seconds"])
        return info


def _prune():
    files = sorted(backup_dir().glob("eko_backup_*.ekobak"), key=lambda p: p.name, reverse=True)
    for old in files[keep_count():]:
        old.unlink(missing_ok=True)


def list_backups() -> list[dict]:
    out = []
    for p in sorted(backup_dir().glob("eko_backup_*.ekobak"), key=lambda p: p.name, reverse=True):
        st = p.stat()
        out.append({"file": p.name, "size_bytes": st.st_size, "modified": int(st.st_mtime)})
    return out


def _open_plain(path: Path) -> zipfile.ZipFile:
    fd, tmp = tempfile.mkstemp(suffix=".zip"); os.close(fd)
    try:
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            crypto_store.decrypt_stream(src, dst)
        zf = zipfile.ZipFile(tmp)
    except BaseException:
        os.unlink(tmp)
        raise
    zf._eko_tmp = tmp  # type: ignore[attr-defined]
    return zf


def _close_plain(zf: zipfile.ZipFile):
    tmp = getattr(zf, "_eko_tmp", None)
    zf.close()
    if tmp:
        try: os.unlink(tmp)
        except OSError: pass


def verify_backup(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = backup_dir() / path
    zf = _open_plain(path)
    try:
        manifest = json.loads(zf.read("manifest.json"))
        problems = []
        for name, expected in manifest["tables"].items():
            with zf.open(f"tables/{name}.jsonl") as f:
                actual = sum(1 for line in f if line.strip())
            if actual != expected:
                problems.append(f"{name}: manifest {expected}, file {actual}")
        return {"ok": not problems, "problems": problems, "created_utc": manifest["created_utc"], "engine": manifest["engine"],
                "rows": sum(manifest["tables"].values()), "tables": manifest["tables"]}
    finally:
        _close_plain(zf)


def restore_backup(path: str | Path, force: bool = False) -> dict:
    """Load a backup into the current database. Refuses a database that already has accounts unless ``force``."""
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = backup_dir() / path
    check = verify_backup(path)
    if not check["ok"]:
        raise ValueError(f"The backup is damaged and was not restored: {check['problems'][:3]}")
    database.init_schema()
    engine = database.get_engine()
    users = metadata.tables["users"]
    with engine.connect() as conn:
        existing = conn.execute(select(func.count()).select_from(users)).scalar()
    if existing and not force:
        raise ValueError("The database already contains accounts. Restoring would overwrite it; run again with force=True (--force) if that is intended.")
    zf = _open_plain(path)
    loaded = {}
    try:
        manifest = json.loads(zf.read("manifest.json"))
        with engine.connect() as conn:
            for table in reversed(metadata.sorted_tables):           # children first
                conn.execute(table.delete())
            conn.commit()
            for table in metadata.sorted_tables:                      # parents first
                wanted = {c.name for c in table.columns}
                total = 0
                with zf.open(f"tables/{table.name}.jsonl") as f:
                    batch = []
                    for line in f:
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        batch.append({k: _dec(v) for k, v in record.items() if k in wanted})
                        if len(batch) >= CHUNK:
                            conn.execute(insert(table), batch); conn.commit(); total += len(batch); batch = []
                    if batch:
                        conn.execute(insert(table), batch); conn.commit(); total += len(batch)
                loaded[table.name] = total
            if engine.dialect.name == "postgresql":
                for table in metadata.sorted_tables:
                    pk = list(table.primary_key.columns)
                    if len(pk) == 1 and pk[0].type.python_type is int:
                        conn.execute(text(f"select setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), greatest((select coalesce(max({pk[0].name}), 0) from {table.name}), 1))"))
                conn.commit()
        bad = {t: (loaded[t], manifest["tables"][t]) for t in loaded if loaded[t] != manifest["tables"].get(t)}
        if bad:
            raise ValueError(f"Restore check failed (loaded, expected): {bad}")
    finally:
        _close_plain(zf)
    return {"restored_from": path.name, "rows": sum(loaded.values()), "tables": loaded}


def auto_backup_if_due(max_age_hours: float = 24.0, label: str = "automatic") -> dict | None:
    """Create a backup unless a recent one exists. Safe to call often; failures are logged, never raised."""
    try:
        newest = max((p.stat().st_mtime for p in backup_dir().glob("eko_backup_*.ekobak")), default=0)
        if time.time() - newest < max_age_hours * 3600:
            return None
        return create_backup(label)
    except Exception as exc:
        _last.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300], at=int(time.time()))
        log.exception("Automatic backup failed")
        return None


def schedule_backup(label: str, max_age_hours: float = 0.5):
    threading.Thread(target=auto_backup_if_due, args=(max_age_hours, label), name="eko-backup", daemon=True).start()


def status() -> dict:
    files = list_backups()
    return {"directory": str(backup_dir()), "count": len(files), "newest": files[0] if files else None, "keep": keep_count(), "last_run": dict(_last)}
