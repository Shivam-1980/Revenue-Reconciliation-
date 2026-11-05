"""Copy platform metadata from local SQLite into a migrated PostgreSQL schema.

Run only after setting DATABASE_URL and applying Alembic migrations. This does not
move financial source workbooks or legacy reconciliation result files.
"""
from __future__ import annotations
import argparse, os, sqlite3, sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE = BACKEND / "data" / "platform.sqlite3"
TABLES = ("organizations", "users", "audit_events", "api_keys", "oidc_login_codes", "background_jobs")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE), help="Source platform.sqlite3 path")
    parser.add_argument("--dry-run", action="store_true", help="Only report source row counts")
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL", "").strip()
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        print("ERROR: set DATABASE_URL to a PostgreSQL connection string first.", file=sys.stderr); return 2
    source_path = Path(args.sqlite).resolve()
    if not source_path.is_file():
        print(f"ERROR: SQLite source not found: {source_path}", file=sys.stderr); return 2
    src = sqlite3.connect(source_path); src.row_factory = sqlite3.Row
    try:
        existing = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows_by_table = {}
        for table in TABLES:
            rows_by_table[table] = [dict(r) for r in src.execute(f'SELECT * FROM "{table}"').fetchall()] if table in existing else []
    finally: src.close()
    counts = {k: len(v) for k, v in rows_by_table.items()}
    print("Source row counts:", counts)
    if args.dry_run: return 0
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        print("ERROR: install backend/requirements.txt to get psycopg.", file=sys.stderr); return 2
    pg_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    conn = psycopg.connect(pg_url, row_factory=dict_row)
    try:
        # Explicit transaction: any conflict/error rolls back all copied rows.
        with conn.transaction():
            for table in TABLES:
                rows = rows_by_table[table]
                if not rows: continue
                columns = list(rows[0].keys())
                col_sql = ",".join('"' + c.replace('"','') + '"' for c in columns)
                placeholders = ",".join(["%s"] * len(columns))
                sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})'
                for row in rows:
                    conn.execute(sql, tuple(row[c] for c in columns))
        print("Migration copy completed. Verify row counts and login/admin APIs before switching production traffic.")
        return 0
    except Exception as exc:
        print(f"ERROR: migration copy rolled back: {exc}", file=sys.stderr)
        return 1
    finally: conn.close()

if __name__ == "__main__": raise SystemExit(main())
