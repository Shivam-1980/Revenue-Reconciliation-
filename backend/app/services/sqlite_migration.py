"""One-time move of an existing SQLite database into PostgreSQL (V62.6.214).

Runs when PostgreSQL is in use, the SQLite file ``platform.sqlite3`` exists, and PostgreSQL has no users yet.
Everything is copied table by table in dependency order (users, API keys, sessions, audit log, uploaded
rows, saved months, ...), row counts are compared, and PostgreSQL id sequences are advanced. The SQLite
file is never changed or deleted; a marker file records the migration so it runs only once.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlalchemy import create_engine, func, insert, select, text

from app import database, db_compat
from app.db_schema import metadata

log = logging.getLogger("eko.migration")
CHUNK = 5000


def marker_path() -> Path:
    return Path(db_compat.DB_PATH).with_name("migrated_to_postgresql.txt")


def migrate_if_needed() -> dict | None:
    sqlite_path = Path(db_compat.DB_PATH)
    if marker_path().exists() or not sqlite_path.exists() or sqlite_path.stat().st_size == 0:
        return None
    target = database.get_engine()
    if target.dialect.name != "postgresql":
        return None
    with target.connect() as conn:
        if conn.execute(select(func.count()).select_from(metadata.tables["users"])).scalar():
            return None                                   # PostgreSQL already holds accounts: never overwrite
    source = create_engine(f"sqlite:///{sqlite_path.as_posix()}", future=True)
    with source.connect() as s:
        have = {r[0] for r in s.execute(text("select name from sqlite_master where type='table'"))}
    copied = {}
    for table in metadata.sorted_tables:                  # parents before children
        if table.name not in have:
            continue
        total = 0
        with source.connect() as s, target.connect() as t:
            t.execute(table.delete()); t.commit()
            result = s.execution_options(stream_results=True).execute(select(table))
            while True:
                rows = result.mappings().fetchmany(CHUNK)
                if not rows:
                    break
                t.execute(insert(table), [dict(r) for r in rows]); t.commit()
                total += len(rows)
        copied[table.name] = total
    with source.connect() as s, target.connect() as t:
        for table in metadata.sorted_tables:
            if table.name not in copied:
                continue
            a = s.execute(select(func.count()).select_from(table)).scalar()
            b = t.execute(select(func.count()).select_from(table)).scalar()
            if a != b:
                raise RuntimeError(f"Migration check failed for {table.name}: SQLite {a} rows, PostgreSQL {b} rows")
            for col in table.primary_key.columns:           # serial ids continue after the copied ones
                if col.autoincrement is True or (col.type.python_type is int and len(table.primary_key.columns) == 1):
                    t.execute(text(f"select setval(pg_get_serial_sequence('{table.name}', '{col.name}'), "
                                   f"greatest((select coalesce(max({col.name}), 0) from {table.name}), 1))"))
        t.commit()
    marker_path().write_text(f"Migrated {sum(copied.values())} rows from {sqlite_path.name} to PostgreSQL on {time.strftime('%Y-%m-%d %H:%M:%S')}.\n"
                             f"Tables: {copied}\nThe SQLite file was not changed and can be deleted once you are satisfied.\n", encoding="utf-8")
    log.warning("Migrated %d rows from SQLite to PostgreSQL: %s", sum(copied.values()), copied)
    return copied
