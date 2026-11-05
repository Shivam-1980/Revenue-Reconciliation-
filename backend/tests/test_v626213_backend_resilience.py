"""The backend must not appear "down" to the browser: locked database, unexpected errors, crashes (V62.6.213)."""
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import database, platform_security as ps
from app.db_schema import src_transaction_rows, src_uploads
from app.main import app
from app.services import db_sync
from test_v626207_database import db, workspace  # noqa: F401  (SQLite + PostgreSQL fixtures)

BACKEND = Path(__file__).resolve().parents[1]


def test_unexpected_error_returns_json_with_cors_headers_not_a_dropped_connection(monkeypatch):
    from app.api import agent_v1
    monkeypatch.setattr(agent_v1, "_conn", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/agent/v1/summary", headers={"Origin": "http://127.0.0.1:5173"})
    assert r.status_code == 500 and "unexpected error" in r.json()["detail"]
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"   # browser can read it


def test_audit_write_failure_does_not_fail_a_successful_request(monkeypatch):
    def locked(*a, **k):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(ps, "record_audit", locked)
    r = TestClient(app).post("/api/workspace/clear-current-data")
    assert r.status_code == 200, r.text


def test_large_sync_is_written_in_chunks_and_matches_the_file(db, workspace, monkeypatch):  # noqa: F811
    monkeypatch.setattr(db_sync, "ROW_CHUNK", 2)
    commits = []
    real = db_sync._bulk_insert
    monkeypatch.setattr(db_sync, "_bulk_insert", lambda conn, table, cols, rows: (commits.append(len(rows)), real(conn, table, cols, rows))[1])
    database.init_schema()
    assert db_sync.sync_workspace("t", "test")["status"] == "ok"
    assert max(commits) <= 2 and sum(1 for n in commits if n) >= 3        # 3 transaction rows -> 2 chunks, plus other sources
    with database.get_engine().connect() as conn:
        assert conn.execute(select(func.count()).select_from(src_transaction_rows)).scalar() == 3
        assert conn.execute(select(src_uploads.c.is_current).where(src_uploads.c.kind == "transactions")).scalar() in (True, 1)


def test_failed_sync_leaves_no_half_written_upload(db, workspace, monkeypatch):  # noqa: F811
    monkeypatch.setattr(db_sync, "ROW_CHUNK", 1)
    real = db_sync._bulk_insert
    calls = {"n": 0}

    def flaky(conn, table, cols, rows):
        calls["n"] += 1
        if table is src_transaction_rows and calls["n"] >= 2:
            raise RuntimeError("disk full")
        return real(conn, table, cols, rows)

    monkeypatch.setattr(db_sync, "_bulk_insert", flaky)
    database.init_schema()
    result = db_sync.sync_workspace("t", "test")
    assert result["status"] == "failed" and "disk full" in result["error"]
    with database.get_engine().connect() as conn:
        assert conn.execute(select(func.count()).select_from(src_uploads).where(src_uploads.c.kind == "transactions")).scalar() == 0
        assert conn.execute(select(func.count()).select_from(src_transaction_rows)).scalar() == 0   # partial rows removed


def test_serve_restarts_the_backend_after_a_crash_and_logs_the_reason(tmp_path):
    """Drive serve.py with a stand-in 'uvicorn' module that crashes once, then exits cleanly."""
    work = tmp_path / "proj"
    (work / "backend" / "uvicorn").mkdir(parents=True)
    (work / "backend" / "serve.py").write_text((BACKEND / "serve.py").read_text(encoding="utf-8"), encoding="utf-8")
    (work / "backend" / "uvicorn" / "__init__.py").write_text("", encoding="utf-8")
    (work / "backend" / "uvicorn" / "__main__.py").write_text(textwrap.dedent("""
        import pathlib, sys
        marker = pathlib.Path(__file__).resolve().parents[2] / "ran_once"
        if not marker.exists():
            marker.write_text("1"); print("simulated crash: segmentation fault"); sys.exit(139)
        print("second start: serving"); sys.exit(0)
    """), encoding="utf-8")
    started = time.time()
    out = subprocess.run([sys.executable, "serve.py"], cwd=work / "backend", capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and time.time() - started < 30
    log = (work / "backend_runtime.log").read_text(encoding="utf-8")
    assert "simulated crash" in log and "stopped unexpectedly (exit code 139)" in log and "restart #1" in log and "second start: serving" in log


def test_start_bat_runs_the_backend_through_the_restarting_launcher():
    bat = (BACKEND.parent / "start.bat").read_text(encoding="ascii")
    assert 'start "EKO Backend" /D "%BACKEND%" "%PY%" serve.py' in bat
    assert (BACKEND / "serve.py").exists()
