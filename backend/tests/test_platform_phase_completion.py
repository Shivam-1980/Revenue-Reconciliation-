import os, sys, time, secrets
from pathlib import Path
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def test_tenant_storage_rejects_traversal(tmp_path, monkeypatch):
    from app.services import tenant_storage
    monkeypatch.setattr(tenant_storage, "STORAGE_ROOT", tmp_path.resolve())
    path = tenant_storage.workspace_dir("eko_org")
    assert path.parent == tmp_path.resolve()
    try:
        tenant_storage.workspace_dir("../outside")
        assert False, "path traversal should be rejected"
    except ValueError:
        pass
    try:
        tenant_storage.resolve_workspace_file("eko_org", "../../escape.txt")
        assert False, "relative traversal should be rejected"
    except ValueError:
        pass


def test_job_queue_is_tenant_scoped(tmp_path, monkeypatch):
    from app.services import platform_jobs
    monkeypatch.setattr(platform_jobs, "DB_PATH", tmp_path / "platform.sqlite3")
    queued = platform_jobs.enqueue("org_one", "user1", "reconciliation", {"period": "dynamic"})
    assert queued["status"] == "queued"
    assert platform_jobs.get_job(queued["id"], "org_one")["id"] == queued["id"]
    assert platform_jobs.get_job(queued["id"], "org_two") is None
    assert platform_jobs.list_jobs("org_two") == []


def test_scoped_api_key_expiry_scope_and_tenant(tmp_path, monkeypatch):
    from app import platform_security as ps
    monkeypatch.setattr(ps, "DB_PATH", tmp_path / "platform.sqlite3")
    conn = ps._db()
    conn.execute("INSERT INTO organizations(id,name,created_at,active) VALUES('org_one','Org One',?,1)", (int(time.time()),))
    conn.commit(); conn.close()
    actor = {"sub": "test-user", "org": "org_one", "role": "org_admin"}
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    # Exercise route behavior through direct helper with deterministic isolated DB.
    conn = ps._db()
    raw = "eko_" + secrets.token_urlsafe(24)
    conn.execute("CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, organization_id TEXT NOT NULL, scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, FOREIGN KEY(organization_id) REFERENCES organizations(id))")
    conn.execute("INSERT INTO api_keys(id,name,key_hash,organization_id,scopes_json,expires_at,created_at) VALUES('k1','test',?,'org_one','[\"audit:read\"]',?,?)",
                 (__import__('hashlib').sha256(raw.encode()).hexdigest(), int(time.time())+300, int(time.time())))
    conn.commit(); conn.close()
    assert ps.verify_scoped_api_key(raw, "audit:read", "org_one")["organization_id"] == "org_one"
    try:
        ps.verify_scoped_api_key(raw, "workspace:admin", "org_one")
        assert False, "missing scope should fail"
    except Exception as e:
        assert getattr(e, "status_code", None) == 403
    try:
        ps.verify_scoped_api_key(raw, "audit:read", "org_two")
        assert False, "wrong tenant should fail"
    except Exception as e:
        assert getattr(e, "status_code", None) == 403
