"""Agent API v1 with real API-key enforcement, on SQLite and (EKO_TEST_DATABASE_URL) PostgreSQL."""
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import database, db_compat
from app import platform_security as ps
from app import security_core as sc
from app.services import db_sync
from test_v626207_database import db, workspace  # noqa: F401  (shared fixtures)

pytestmark = pytest.mark.real_auth
API = "/api/agent/v1"


@pytest.fixture
def agent(db, workspace, monkeypatch):  # noqa: F811
    if db == "sqlite":
        monkeypatch.setattr(ps, "DB_PATH", db_compat.DB_PATH)
    database.init_schema()
    sc.initialize_security_schema()
    now = int(time.time())
    with database.get_engine().begin() as conn:
        conn.execute(text("INSERT INTO organizations(id,name,created_at,active) VALUES('eko','Eko',:n,1)"), {"n": now})
    assert db_sync.sync_workspace("setup", "test")["status"] == "ok"
    from app.main import app
    client = TestClient(app)

    def key(*scopes, revoked=0, expires_in=3600):
        raw = "eko_test_" + hashlib.sha256(f"{scopes}{revoked}{expires_in}{time.time_ns()}".encode()).hexdigest()[:40]
        with database.get_engine().begin() as conn:
            conn.execute(text("INSERT INTO api_keys(id,name,key_hash,organization_id,scopes_json,expires_at,revoked,created_at) "
                              "VALUES(:i,:n,:h,'eko',:s,:e,:r,:c)"),
                         {"i": raw[-12:], "n": "agent-" + "-".join(scopes), "h": hashlib.sha256(raw.encode()).hexdigest(),
                          "s": json.dumps(list(scopes)), "e": now + expires_in, "r": revoked, "c": now})
        return {"X-API-Key": raw}

    return client, key


def test_requires_valid_key(agent):
    client, key = agent
    assert client.get(f"{API}/summary").status_code == 401
    assert client.get(f"{API}/summary", headers={"X-API-Key": "eko_wrong"}).status_code == 401
    assert client.get(f"{API}/summary", headers=key("*", revoked=1)).status_code == 401
    assert client.get(f"{API}/summary", headers=key("*", expires_in=-5)).status_code == 401


def test_scopes_are_enforced(agent):
    client, key = agent
    read, write, admin = key("read"), key("write"), key("admin")
    assert client.get(f"{API}/summary", headers=read).status_code == 200
    assert client.post(f"{API}/sync", headers=read).status_code == 403
    assert client.get(f"{API}/audit-events", headers=read).status_code == 403
    assert client.post(f"{API}/sync", headers=write).status_code == 200
    assert client.get(f"{API}/audit-events", headers=write).status_code == 403
    assert client.get(f"{API}/audit-events", headers=admin).status_code == 200
    assert client.get("/api/auth/users", headers=admin).status_code == 200
    assert client.get(f"{API}/summary", headers=key("reconciliation:read")).status_code == 200  # legacy alias


def test_full_access_key_can_administer_users_and_keys(agent):
    client, key = agent
    full = key("*")
    r = client.post("/api/auth/users", headers=full, json={"email": "new.operator@eko.test", "password": "A-Very-Long-Pass-123",
                                                          "role": "operator", "organization_id": "eko"})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/api-keys", headers=full, json={"name": "child", "scopes": ["read"], "organization_id": "eko", "expires_in_days": 5})
    assert r.status_code == 201, r.text
    child = {"X-API-Key": r.json()["api_key"]}
    assert client.get(f"{API}/summary", headers=child).status_code == 200
    listed = client.get("/api/auth/api-keys", headers=full).json()["items"]
    assert any(k["name"] == "child" and k["active"] for k in listed) and all("key_hash" not in k for k in listed)
    assert client.post(f"/api/auth/api-keys/{r.json()['id']}/revoke", headers=full).status_code == 200
    assert client.get(f"{API}/summary", headers=child).status_code == 401
    events = client.get(f"{API}/audit-events", headers=full, params={"event_type": "api_key.created"}).json()["items"]
    assert events and events[0]["detail"]["scopes"] == ["read"]


def test_capabilities_and_summary(agent):
    client, key = agent
    caps = client.get(f"{API}/capabilities", headers=key("read")).json()
    assert caps["principal"]["scopes"] == ["read"] and any("/runs/{run_id}/results" in e for e in caps["read"])
    assert any("rules" in e for e in caps["not_available"])
    s = client.get(f"{API}/summary", headers=key("read")).json()
    assert {u["kind"] for u in s["current_uploads"]} == {"transactions", "commission", "women_csp_roster"}
    assert s["current_run"]["run_id"] == "REC-1" and s["history_periods"] == ["2026-09"]


def test_transactions_pagination_and_exact_money(agent):
    client, key = agent
    h = key("read")
    p1 = client.get(f"{API}/transactions", headers=h, params={"limit": 2}).json()
    assert [r["transaction_id"] for r in p1["items"]] == ["T1", "T2"] and p1["next_cursor"] == 2
    assert p1["items"][0]["amount"] == "1000.5" and p1["items"][1]["amount"] == "2500"
    assert p1["items"][1]["extra"]["to_account"] == "****" and p1["upload"]["period_start"] == "2026-09-10"
    p2 = client.get(f"{API}/transactions", headers=h, params={"limit": 2, "after_row": p1["next_cursor"]}).json()
    assert [r["transaction_id"] for r in p2["items"]] == ["T3"] and p2["items"][0]["amount"] is None and p2["next_cursor"] is None
    only = client.get(f"{API}/transactions", headers=h, params={"csp_id": "1a850002"}).json()
    assert [r["transaction_id"] for r in only["items"]] == ["T3"]
    cm = client.get(f"{API}/commissions", headers=h).json()["items"]
    assert [c["actual_commission"] for c in cm] == ["30", "12.3456"]


def test_runs_results_history_and_csp_view(agent):
    client, key = agent
    h = key("read")
    assert client.get(f"{API}/runs", headers=h).json()["items"][0]["run_id"] == "REC-1"
    run = client.get(f"{API}/runs/current", headers=h).json()
    assert run["expected_commission"] == "45.5" and run["variance"] is None and run["result_rows"] == 2
    exc = client.get(f"{API}/runs/REC-1/results", headers=h, params={"exceptions_only": True}).json()
    assert [r["csp_id"] for r in exc["items"]] == ["1A850002"] and exc["items"][0]["expected_commission"] is None
    assert client.get(f"{API}/runs/NOPE", headers=h).status_code == 404
    snap = client.get(f"{API}/history/2026-09", headers=h).json()
    assert snap["snapshot"]["summary"]["variance"] is None
    csp = client.get(f"{API}/csps/1a850001", headers=h).json()
    assert csp["transactions_by_type"][0]["amount"] == "1000.5"
    assert csp["bc_commission_rows"][0]["actual_commission"] == "30"
    assert csp["supplemental"]["women_csp_roster"][0]["data"]["transaction_count"] == "573"
    assert csp["reconciliation_results"][0]["reconciliation_status"] == "MATCH"
    assert client.get(f"{API}/csps/UNKNOWN1", headers=h).status_code == 404


def test_new_month_is_current_and_old_month_stays_reachable(agent, workspace):  # noqa: F811
    client, key = agent
    h, w = key("read"), key("write")
    old_id = client.get(f"{API}/transactions", headers=h).json()["upload"]["id"]
    (workspace / "transactions" / "latest_transactions.csv").write_text(
        "ko_id,transaction_date,transaction_id,transaction_type,from_account,to_account,amount,status,new_date,csp_id\n"
        "9,2026-10-01,OCT1,Money Transfer,,,77,SUCCESS,,1A850009\n", encoding="utf-8")
    assert client.post(f"{API}/sync", headers=w).status_code == 200
    current = client.get(f"{API}/transactions", headers=h).json()
    assert [r["transaction_id"] for r in current["items"]] == ["OCT1"]
    old = client.get(f"{API}/transactions", headers=h, params={"upload_id": old_id}).json()
    assert len(old["items"]) == 3
    kinds = client.get(f"{API}/uploads", headers=h, params={"kind": "transactions"}).json()["items"]
    assert sorted(u["is_current"] for u in kinds) == [False, True]
