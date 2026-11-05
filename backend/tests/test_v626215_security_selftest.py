"""Attack-style self-test over EVERY route: nothing under /api works without a session, viewers cannot change data,
injection/traversal probes never leak internals, and responses carry the hardening headers."""
import re
import time

import pytest
from fastapi.testclient import TestClient

from app import platform_security as ps
from app import security_core as sc
from app.main import app

pytestmark = pytest.mark.real_auth
PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(ps, "DB_PATH", tmp_path / "platform.sqlite3")
    monkeypatch.setattr(ps, "USE_POSTGRES", False)
    sc.initialize_security_schema()
    conn = ps._db(); now = int(time.time())
    conn.execute("INSERT INTO organizations(id,name,created_at,active) VALUES('eko','Eko',?,1)", (now,))
    conn.execute("INSERT INTO users(id,email,password_hash,role,organization_id,active,created_at) VALUES('u-view','view@eko.test',?, 'viewer','eko',1,?)",
                 (ps._password_hash(PASSWORD), now))
    conn.commit(); conn.close()
    return {}


def _api_routes():
    """Every (method, path) the API publishes. The OpenAPI schema is used because newer FastAPI nests included routers."""
    out = set()
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api/"):
            for method in ops:
                if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                    out.add((method.upper(), re.sub(r"\{[^}]+\}", "1", path)))
    return sorted(out)


def test_every_api_route_rejects_anonymous_callers(env):
    c = TestClient(app)
    public = sc.PUBLIC_PATHS
    leaks = []
    assert len(_api_routes()) > 60, "route inventory looks empty"
    for method, path in _api_routes():
        if path in public or any(path.startswith(p) for p in public if p.endswith("/")):
            continue
        r = c.request(method, path)
        if r.status_code not in (401, 403):
            leaks.append(f"{method} {path} -> {r.status_code}")
    assert not leaks, "routes answering without a session:\n" + "\n".join(leaks)


def _viewer(env):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": "view@eko.test", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c, r.json().get("csrf_token") or c.cookies.get("csrf")


def test_viewer_cannot_change_anything_and_probes_do_not_leak(env):
    c, csrf = _viewer(env)
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    allowed_writes = {"/api/auth/logout"}
    changed = []
    assert sum(1 for m, _ in _api_routes() if m != "GET") > 20
    for method, path in _api_routes():
        if method in ("POST", "PUT", "PATCH", "DELETE") and not path.startswith("/api/auth/") and path not in allowed_writes:
            r = c.request(method, path, headers=headers)
            if r.status_code < 400 or r.status_code >= 500:
                changed.append(f"{method} {path} -> {r.status_code}")
    assert not changed, "a viewer reached a write route:\n" + "\n".join(changed)
    for evil in ("' OR 1=1 --", "../../../../etc/passwd", r"..\..\windows\win.ini", "<script>alert(1)</script>", "%00"):
        for path in ("/api/reconciliation/csp", "/api/trace/transactions", "/api/reconciliation/history/2026-09"):
            r = c.get(path, params={"search": evil, "csp_id": evil, "q": evil})
            body = r.text.lower()
            assert r.status_code < 500 or r.status_code == 503, (path, evil, r.status_code)
            assert "traceback" not in body and "sqlalchemy" not in body and "sqlite3" not in body and "psycopg" not in body
            assert "root:x:" not in body and "[extensions]" not in body


def test_security_headers_present_on_api_and_error_responses(env):
    c = TestClient(app)
    for r in (c.get("/health"), c.get("/api/version"), c.get("/api/does-not-exist")):
        h = {k.lower(): v for k, v in r.headers.items()}
        assert h.get("x-content-type-options") == "nosniff" and h.get("x-frame-options") == "DENY"
        assert "referrer-policy" in h and "permissions-policy" in h
        assert "x-powered-by" not in h and "server" not in {k for k in h if "uvicorn" in h[k].lower()}


def test_security_checklist_reports_actions_without_changing_anything(monkeypatch, tmp_path):
    from app.services import security_posture as sp
    monkeypatch.setattr(sp, "DATA", tmp_path)
    monkeypatch.setattr(sp, "KEY_EXPORT_MARKER", tmp_path / "key_exported.txt")
    monkeypatch.setenv("EKO_HTTPS", "false"); monkeypatch.delenv("EKO_BACKUP_DIR", raising=False)
    r = sp.posture()
    by = {c["id"]: c for c in r["checks"]}
    assert by["https"]["status"] == "action" and by["key_copy"]["status"] == "action" and by["backup_location"]["status"] == "action"
    (tmp_path / "key_exported.txt").write_text("x")
    monkeypatch.setenv("EKO_HTTPS", "true")
    r2 = {c["id"]: c for c in sp.posture()["checks"]}
    assert r2["https"]["status"] == "ok" and r2["key_copy"]["status"] == "ok"
    assert r["ok"] + r["action"] + r["unknown"] == len(r["checks"])


def test_security_checklist_endpoint_is_admin_only(env):
    c, _ = _viewer(env)
    assert c.get("/api/database/security-posture").status_code == 403


def test_security_checklist_has_no_email_code_or_smtp_items(env):
    from app.services import security_posture
    ids = {c["id"] for c in security_posture.posture()["checks"]}
    assert {"database", "https"} <= ids
    assert "two_step" not in ids and "smtp" not in ids
