"""Small DB-API compatibility layer for platform metadata: SQLite locally, PostgreSQL when DATABASE_URL is set.
Only platform metadata/jobs use this module; legacy financial workbooks remain on their existing local path.
"""
from __future__ import annotations
import os, re, sqlite3
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("PLATFORM_DB_PATH", str(BACKEND_DIR / "data" / "platform.sqlite3")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# EKO_DATABASE=embedded: use the built-in PostgreSQL (started on demand, see app/embedded_pg.py).
# An explicit DATABASE_URL always wins; EKO_DATABASE=sqlite keeps the local SQLite file.
if not DATABASE_URL and os.getenv("EKO_DATABASE", "sqlite").strip().lower() == "embedded":
    from app import embedded_pg
    DATABASE_URL = embedded_pg.ensure_running()
    os.environ["DATABASE_URL"] = DATABASE_URL     # child processes (uvicorn workers, tools) reuse the same server
USE_POSTGRES = DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://"))

class _Result:
    def __init__(self, cursor): self.cursor = cursor
    def fetchone(self): return self.cursor.fetchone()
    def fetchall(self): return self.cursor.fetchall()

class PostgresCompatConnection:
    def __init__(self, conn): self._conn = conn
    def execute(self, sql, params=()):
        # SQL statements in platform modules use positional '?' placeholders; psycopg uses '%s'.
        sql = sql.replace("?", "%s")
        return _Result(self._conn.execute(sql, params or ()))
    def commit(self): self._conn.commit()
    def close(self): self._conn.close()
    def rollback(self): self._conn.rollback()

def connect_platform():
    if USE_POSTGRES:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL selects PostgreSQL but psycopg is not installed. Install backend/requirements.txt.") from exc
        url = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
        return PostgresCompatConnection(psycopg.connect(url, row_factory=dict_row, connect_timeout=8))
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def initialize_sqlite_schema(conn):
    if USE_POSTGRES: return
    conn.execute("""CREATE TABLE IF NOT EXISTS organizations (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('super_admin','org_admin','operator','viewer')), organization_id TEXT, active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, FOREIGN KEY(organization_id) REFERENCES organizations(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id TEXT, organization_id TEXT, event_type TEXT NOT NULL, detail_json TEXT NOT NULL, created_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, organization_id TEXT NOT NULL, scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, FOREIGN KEY(organization_id) REFERENCES organizations(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS oidc_login_codes (code_hash TEXT PRIMARY KEY, access_token TEXT NOT NULL, expires_at INTEGER NOT NULL)""")
    conn.commit()

def integrity_errors():
    errors = [sqlite3.IntegrityError]
    try:
        import psycopg
        errors.append(psycopg.IntegrityError)
    except ImportError: pass
    return tuple(errors)
