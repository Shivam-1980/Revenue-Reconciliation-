"""SQLAlchemy engine for the unified database (V62.6.207).

PostgreSQL when DATABASE_URL is set (required in hosted mode); otherwise the local SQLite
file that the platform already uses, so a desktop install keeps working without PostgreSQL.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine

from app import db_compat
from app.db_schema import metadata

_engines: dict[str, Engine] = {}
_lock = threading.Lock()


def database_url() -> str:
    url = (db_compat.DATABASE_URL or "").strip()
    if url:
        # Always use the psycopg 3 driver (installed via psycopg[binary]).
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    if os.getenv("APP_ENV", "local").strip().lower() in {"production", "hosted"}:
        raise RuntimeError("DATABASE_URL (PostgreSQL) must be set in hosted/production mode.")
    path = Path(db_compat.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def is_postgres(engine: Engine | None = None) -> bool:
    return (engine or get_engine()).dialect.name == "postgresql"


def get_engine() -> Engine:
    url = database_url()
    with _lock:
        engine = _engines.get(url)
        if engine is None:
            if url.startswith("sqlite"):
                engine = create_engine(url, connect_args={"timeout": 30, "check_same_thread": False}, future=True)

                @event.listens_for(engine, "connect")
                def _sqlite_pragmas(dbapi_conn, _record):
                    cur = dbapi_conn.cursor()
                    cur.execute("PRAGMA foreign_keys=ON")
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.close()
            else:
                engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10, future=True,
                                       connect_args={"connect_timeout": 8})
            _engines[url] = engine
        return engine


def init_schema() -> None:
    """Create any missing tables (idempotent; existing tables and data are untouched)."""
    metadata.create_all(get_engine(), checkfirst=True)
    if is_postgres() and (os.getenv("EKO_DATABASE", "").strip().lower() == "embedded" or os.getenv("EKO_MIGRATE_SQLITE", "").strip().lower() == "true"):
        try:
            from app.services import sqlite_migration
            sqlite_migration.migrate_if_needed()
        except Exception:
            import logging
            logging.getLogger("eko.migration").exception("SQLite -> PostgreSQL data migration failed; the SQLite file was left untouched")
            raise


def describe() -> dict:
    """Connection summary without credentials."""
    engine = get_engine()
    info = {"engine": engine.dialect.name, "database": engine.url.database}
    if engine.dialect.name == "postgresql":
        info.update({"host": engine.url.host, "port": engine.url.port})
    with engine.connect() as conn:
        info["server_version"] = (conn.execute(text("select version()")).scalar() if engine.dialect.name == "postgresql"
                                  else "SQLite " + conn.execute(text("select sqlite_version()")).scalar())
        info["tables"] = sorted(inspect(conn).get_table_names())
    return info
