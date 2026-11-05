"""Small durable SQLite job queue foundation; workers are started separately.
Does not alter synchronous legacy reconciliation endpoints."""
import json, os, sqlite3, time, uuid
from pathlib import Path
from typing import Any
from app.db_compat import connect_platform, USE_POSTGRES

BACKEND_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("PLATFORM_DB_PATH", str(BACKEND_DIR / "data" / "platform.sqlite3")))

def _conn():
    if USE_POSTGRES:
        # The Alembic migration creates this table before hosted workers are enabled.
        return connect_platform()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("""CREATE TABLE IF NOT EXISTS background_jobs (
      id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, created_by TEXT NOT NULL,
      job_type TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
      created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      result_json TEXT, error TEXT
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_org_status ON background_jobs(organization_id,status,created_at)")
    c.commit(); return c


def enqueue(organization_id: str, created_by: str, job_type: str, payload: dict[str, Any]):
    if job_type not in {"file_validation", "reconciliation", "report_export"}:
        raise ValueError("Unsupported job type")
    job_id = uuid.uuid4().hex
    now = int(time.time())
    c = _conn()
    try:
        c.execute("INSERT INTO background_jobs(id,organization_id,created_by,job_type,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?)",
                  (job_id, organization_id, created_by, job_type, json.dumps(payload, separators=(",",":"), default=str), now, now))
        c.commit()
        return {"id": job_id, "organization_id": organization_id, "job_type": job_type, "status": "queued", "created_at": now}
    finally: c.close()

def get_job(job_id: str, organization_id: str):
    c = _conn()
    try:
        row = c.execute("SELECT id,organization_id,created_by,job_type,status,created_at,updated_at,attempts,result_json,error FROM background_jobs WHERE id=? AND organization_id=?", (job_id, organization_id)).fetchone()
        if not row: return None
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
        return d
    finally: c.close()

def list_jobs(organization_id: str, limit: int = 50):
    c = _conn()
    try:
        rows = c.execute("SELECT id,organization_id,created_by,job_type,status,created_at,updated_at,attempts,error FROM background_jobs WHERE organization_id=? ORDER BY created_at DESC LIMIT ?", (organization_id, max(1,min(limit,200)))).fetchall()
        return [dict(r) for r in rows]
    finally: c.close()
