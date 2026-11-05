"""Workspace -> database sync on SQLite and (when EKO_TEST_DATABASE_URL is set) real PostgreSQL."""
import json
import os
import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from fastapi.testclient import TestClient

from app import database, db_compat
from app import platform_security as ps
from app import security_core as sc
from app.db_schema import (db_sync_log, recon_history_snapshots, recon_result_rows, recon_runs, src_commission_rows,
                           src_generic_rows, src_transaction_rows, src_uploads)
from app.services import db_sync

PG_URL = os.getenv("EKO_TEST_DATABASE_URL", "").strip()
BACKENDS = ["sqlite"] + (["postgresql"] if PG_URL else [])


@pytest.fixture(params=BACKENDS)
def db(request, monkeypatch, tmp_path):
    if request.param == "sqlite":
        monkeypatch.setattr(db_compat, "DATABASE_URL", "")
        monkeypatch.setattr(db_compat, "DB_PATH", tmp_path / "eko.sqlite3")
        yield request.param
        return
    name = "eko_test_" + uuid.uuid4().hex[:10]
    admin = create_engine(PG_URL.replace("postgresql://", "postgresql+psycopg://", 1), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = PG_URL.rsplit("/", 1)[0] + "/" + name
    monkeypatch.setattr(db_compat, "DATABASE_URL", url)
    monkeypatch.setattr(db_compat, "USE_POSTGRES", True)
    monkeypatch.setattr(ps, "USE_POSTGRES", True)
    yield request.param
    for engine in list(database._engines.values()):
        engine.dispose()
    database._engines.clear()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    data = tmp_path / "data"
    for sub in ("transactions", "commissions", "supplemental", "audit", "reconciliation_history"):
        (data / sub).mkdir(parents=True)
    (data / "transactions" / "latest_transactions.csv").write_text(
        "ko_id,transaction_date,transaction_id,transaction_type,from_account,to_account,amount,status,new_date,csp_id\n"
        "1,2026-09-10,T1,AEPS ONUS Withdrawal,111,,1000.50,SUCCESS,,1A850001\n"
        "2,2026-09-11,T2,Money Transfer,222,333,2500,SUCCESS,,1A850001\n"
        "3,2026-09-12,T3,Money Transfer,,,not-a-number,SUCCESS,,1A850002\n", encoding="utf-8")
    (data / "commissions" / "latest_commission.csv").write_text(
        "circle,circle_name,bc_code,csp_id,csp_name,transaction_type,report_base,actual_commission,channel\n"
        "1,Patna,1A85,1A850001,SAMPLE AGENT,AEPS ONUS WITHDRAWAL,1,30,RURAL\n"
        "1,Patna,1A85,1A850002,RAM,MONEY TRANSFER,2,12.3456,URBAN\n", encoding="utf-8")
    (data / "supplemental" / "latest_women_csp_roster.csv").write_text(
        "csp_id,csp_name,transaction_count,period\n1A850001,Sample Agent,573,2026-09\n", encoding="utf-8")
    (data / "audit" / "run_log.csv").write_text(
        "run_id,run_at_utc,transaction_period_start,transaction_period_end,transaction_sha256,commission_sha256,rate_master_sha256,"
        "successful_transactions,exception_groups,expected_commission,actual_commission,variance,settlement_ready\n"
        "REC-1,2026-10-28T08:00:00+00:00,2026-09-10,2026-09-12,txsha,cmsha,rmsha,3,1,45.5,42.3456,,False\n", encoding="utf-8")
    (data / "reconciliation_cache.csv").write_text(
        "csp_id,transaction_type,join_type,successful_transactions,transaction_amount,expected_commission,actual_comparable_commission,"
        "financial_gap,reconciliation_status,exception_flag,mismatch_reason,rate_rule_applied\n"
        "1A850001,AEPS ONUS WITHDRAWAL,AEPS ONUS WITHDRAWAL,1,1000.5,30,30,0,MATCH,False,,1\n"
        "1A850002,MONEY TRANSFER,MONEY TRANSFER,1,,,,,EVIDENCE_REQUIRED,True,Geography missing,0\n", encoding="utf-8")
    (data / "reconciliation_cache_meta.json").write_text(json.dumps({"signature": {"transactions": "txsha", "commission": "cmsha",
                                                                                     "engine_version": "test-engine"}}), encoding="utf-8")
    (data / "reconciliation_history" / "2026-09.json").write_text(
        '{"period_key": "2026-09", "saved_at": "2026-10-28", "summary": {"variance": NaN, "rows": 2}}', encoding="utf-8")
    monkeypatch.setattr(db_sync, "DATA", data)
    monkeypatch.setattr(db_sync, "RUN_LOG", data / "audit" / "run_log.csv")
    monkeypatch.setattr(db_sync, "CACHE", data / "reconciliation_cache.csv")
    monkeypatch.setattr(db_sync, "CACHE_META", data / "reconciliation_cache_meta.json")
    monkeypatch.setattr(db_sync, "HISTORY_DIR", data / "reconciliation_history")
    meta = {"transactions": {"filename": "Success Sep.xlsx", "period_start": "2026-09-10", "period_end": "2026-09-12", "batch_id": "b1"},
            "commission": {"filename": "BC Report Sep.xlsx"}, "women_csp_roster": {"filename": "Women_CSP_Sep.xlsx"}}
    monkeypatch.setattr("app.services.upload_metadata.load_metadata", lambda: meta)
    return data


def _count(conn, table, *where):
    q = select(func.count()).select_from(table)
    for w in where:
        q = q.where(w)
    return conn.execute(q).scalar()


def test_sync_records_sources_runs_and_history(db, workspace):
    database.init_schema()
    result = db_sync.sync_workspace("tester@eko.test", "test")
    assert result["status"] == "ok", result
    with database.get_engine().connect() as conn:
        uploads = {r.kind: r for r in conn.execute(select(src_uploads)).all()}
        assert set(uploads) == {"transactions", "commission", "women_csp_roster"}
        assert uploads["transactions"].filename == "Success Sep.xlsx" and uploads["transactions"].period_start == "2026-09-10"
        assert uploads["transactions"].row_count == 3 and uploads["transactions"].is_current
        tx = conn.execute(select(src_transaction_rows).order_by(src_transaction_rows.c.row_no)).all()
        assert [Decimal(str(r.amount)) if r.amount is not None else None for r in tx] == [Decimal("1000.50"), Decimal("2500"), None]
        assert tx[0].csp_id == "1A850001" and tx[1].extra["to_account"] == "****"
        cm = conn.execute(select(src_commission_rows).order_by(src_commission_rows.c.row_no)).all()
        assert Decimal(str(cm[1].actual_commission)) == Decimal("12.3456") and cm[0].extra["csp_name"] == "SAMPLE AGENT"
        women = conn.execute(select(src_generic_rows)).one()
        assert women.csp_id == "1A850001" and women.data["transaction_count"] == "573"
        run = conn.execute(select(recon_runs)).one()
        assert run.run_id == "REC-1" and run.is_current and run.result_rows == 2 and run.engine_version == "test-engine"
        assert Decimal(str(run.expected_commission)) == Decimal("45.5") and run.variance is None
        rows = conn.execute(select(recon_result_rows).order_by(recon_result_rows.c.row_no)).all()
        assert rows[0].reconciliation_status == "MATCH" and rows[0].exception_flag is False
        assert rows[1].expected_commission is None and rows[1].data["rate_rule_applied"] == "0"
        snap = conn.execute(select(recon_history_snapshots)).one()
        assert snap.period_key == "2026-09" and snap.snapshot["summary"]["variance"] is None
        assert _count(conn, db_sync_log, db_sync_log.c.status == "ok") == 1


def test_resync_is_idempotent_and_new_upload_keeps_history(db, workspace):
    database.init_schema()
    db_sync.sync_workspace("a", "t1")
    assert db_sync.sync_workspace("a", "t2")["sources"]["added"] == []
    tx_file = workspace / "transactions" / "latest_transactions.csv"
    tx_file.write_text(tx_file.read_text(encoding="utf-8") + "4,2026-09-13,T4,Money Transfer,,,10,SUCCESS,,1A850003\n", encoding="utf-8")
    added = db_sync.sync_workspace("a", "t3")["sources"]["added"]
    assert added == [{"kind": "transactions", "rows": 4}]
    with database.get_engine().connect() as conn:
        assert _count(conn, src_uploads, src_uploads.c.kind == "transactions") == 2
        assert _count(conn, src_uploads, src_uploads.c.kind == "transactions", src_uploads.c.is_current.is_(True)) == 1
        assert _count(conn, src_transaction_rows) == 3 + 4  # previous month's rows are retained, not overwritten
        assert _count(conn, recon_runs) == 1 and _count(conn, recon_result_rows) == 2


def test_startup_reset_retires_but_never_deletes(db, workspace):
    database.init_schema()
    db_sync.sync_workspace("a", "t1")
    (workspace / "transactions" / "latest_transactions.csv").unlink()
    assert "transactions" in db_sync.sync_workspace("system", "startup")["sources"]["retired"]
    with database.get_engine().connect() as conn:
        assert _count(conn, src_uploads, src_uploads.c.kind == "transactions", src_uploads.c.is_current.is_(True)) == 0
        assert _count(conn, src_transaction_rows) == 3


def test_failed_sync_is_logged_not_raised(db, workspace, monkeypatch):
    database.init_schema()
    monkeypatch.setattr(db_sync, "sync_runs", lambda conn, actor: (_ for _ in ()).throw(RuntimeError("boom")))
    result = db_sync.sync_workspace("a", "t")
    assert result["status"] == "failed" and "boom" in result["error"]
    with database.get_engine().connect() as conn:
        assert _count(conn, db_sync_log, db_sync_log.c.status == "failed") == 1


def test_database_api_reports_status_and_restricts_manual_sync(db, workspace, monkeypatch):
    database.init_schema()
    from app.main import app
    client = TestClient(app)
    status = client.get("/api/database/status").json()
    assert status["connected"] is True and status["engine"] == db
    assert client.post("/api/database/sync").json()["status"] == "ok"
    assert client.get("/api/database/status").json()["counts"]["current_uploads"] == 3
    monkeypatch.setattr(sc, "authenticate_request", lambda req: {"sub": "op", "role": "operator", "via": "test"})
    assert client.post("/api/database/sync").status_code == 403


@pytest.mark.real_auth
def test_password_session_flow_works_on_this_database(db, monkeypatch):
    database.init_schema()
    sc.initialize_security_schema()
    if db == "sqlite":
        monkeypatch.setattr(ps, "DB_PATH", db_compat.DB_PATH)
    with database.get_engine().begin() as conn:
        now = int(time.time())
        conn.execute(text("INSERT INTO organizations(id,name,created_at,active) VALUES('eko','Eko',:n,1)"), {"n": now})
        conn.execute(text("INSERT INTO users(id,email,password_hash,role,organization_id,active,created_at) "
                          "VALUES('u1','pg@eko.test',:h,'super_admin','eko',1,:n)"), {"h": ps._password_hash("Postgres-Pass-123"), "n": now})
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"email": "pg@eko.test", "password": "Postgres-Pass-123"})
    assert r.status_code == 200, r.text
    assert "mfa_required" not in r.json() and r.json()["csrf_token"]
    assert client.get("/api/database/status").json()["engine"] == db
    with database.get_engine().connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM audit_events WHERE event_type='auth.login_succeeded'")).scalar() == 1
