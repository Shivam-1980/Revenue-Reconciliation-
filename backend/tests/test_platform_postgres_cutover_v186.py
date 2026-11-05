from app.db_compat import connect_platform, initialize_sqlite_schema, USE_POSTGRES
from app import platform_security


def test_platform_db_backend_is_explicit_and_local_default_is_sqlite():
    # CI runs without DATABASE_URL; local desktop mode must retain SQLite compatibility.
    assert USE_POSTGRES is False
    conn = connect_platform()
    try:
        initialize_sqlite_schema(conn)
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='organizations'").fetchone()
        assert row is not None
    finally:
        conn.close()


def test_postgres_migration_guide_preserves_hosted_fail_closed_boundary():
    from pathlib import Path
    guide = Path(__file__).resolve().parents[1] / "migrations" / "README.md"
    text = guide.read_text(encoding="utf-8").lower()
    assert "alembic upgrade head" in text
    assert "fail-closed" in text
    assert "financial source workbooks" in text
