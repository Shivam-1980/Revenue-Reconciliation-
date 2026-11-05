"""Real authentication enforcement: password sign-in, sessions, CSRF, roles, API keys."""
import base64
import hashlib
import hmac
import json
import sqlite3
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import platform_security as ps
from app import security_core as sc
from app.main import app

pytestmark = pytest.mark.real_auth
PASSWORD = "Correct-Horse-Battery-9"
PROBE = "/api/test-auth-probe"  # harmless state-changing route; still passes through all middleware


def _probe():
    return {"ok": True}


if not any(getattr(r, "path", None) == PROBE for r in app.routes):
    app.add_api_route(PROBE, _probe, methods=["POST", "DELETE"])


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(ps, "DB_PATH", tmp_path / "platform.sqlite3")
    monkeypatch.setattr(ps, "USE_POSTGRES", False)
    sc.initialize_security_schema()
    conn = ps._db()
    now = int(time.time())
    conn.execute("INSERT INTO organizations(id,name,created_at,active) VALUES('eko','Eko',?,1)", (now,))
    for uid, email, role in [("u-admin", "admin@eko.test", "org_admin"), ("u-op", "op@eko.test", "operator"), ("u-view", "view@eko.test", "viewer")]:
        conn.execute("INSERT INTO users(id,email,password_hash,role,organization_id,active,created_at) VALUES(?,?,?,?, 'eko',1,?)",
                     (uid, email, ps._password_hash(PASSWORD), role, now))
    conn.commit(); conn.close()
    return {"client": TestClient(app), "db": tmp_path / "platform.sqlite3"}


def sign_in(env, email="admin@eko.test"):
    r = env["client"].post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r


def test_business_api_requires_sign_in_but_health_is_public(env):
    c = env["client"]
    assert c.get("/health").status_code == 200
    assert c.get("/api/version").status_code == 200
    for path in ("/api/reconciliation/status", "/api/dashboard/summary", "/api/reconciliation/export", "/api/auth/users"):
        assert c.get(path).status_code == 401, path
    # The page-load session question is public but reveals nothing when signed out.
    assert c.get("/api/auth/session").json() == {"signed_in": False}
    r = c.post(PROBE)
    assert r.status_code == 401
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_full_login_issues_httponly_strict_session_cookie(env):
    r = sign_in(env)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    body = r.json()
    assert body["user"]["email"] == "admin@eko.test" and body["csrf_token"]
    c = env["client"]
    assert c.get("/api/reconciliation/status").status_code == 200
    s = c.get("/api/auth/session").json()
    assert s["via"] == "session" and s["user"]["role"] == "org_admin"


def test_login_opens_the_session_directly_with_no_second_step(env):
    c = env["client"]
    r = c.post("/api/auth/login", json={"email": "admin@eko.test", "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "mfa_required" not in body and "challenge_id" not in body and "access_token" not in body
    assert body["csrf_token"] and body["user"]["email"] == "admin@eko.test"
    assert c.get("/api/reconciliation/status").status_code == 200


def test_no_credentials_means_no_access(env):
    assert env["client"].get("/api/reconciliation/status").status_code == 401


def test_old_code_verification_endpoints_are_gone_and_open_nothing(env):
    c = TestClient(app)
    for path, body in (("/api/auth/login/verify", {"challenge_id": "x" * 24, "code": "123456"}),
                       ("/api/auth/login/resend", {"challenge_id": "x" * 24})):
        r = c.post(path, json=body)
        assert r.status_code in (401, 404, 405), (path, r.status_code)
        assert "session" not in r.cookies and "csrf_token" not in r.text
    assert c.get("/api/reconciliation/status").status_code == 401


def test_status_reports_no_second_step(env):
    assert TestClient(app).get("/api/auth/status").json()["two_factor"] == "none"
    assert "two_factor_disabled" not in sign_in(env).json()


def test_wrong_password_is_generic_and_locks_after_five(env):
    c = env["client"]
    for _ in range(5):
        r = c.post("/api/auth/login", json={"email": "admin@eko.test", "password": "wrong-password-123"})
        assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."
    sc.rate_limiter.reset()
    r = c.post("/api/auth/login", json={"email": "admin@eko.test", "password": PASSWORD})
    assert r.status_code == 429 and "Try again" in r.json()["detail"]


def test_unknown_email_gets_same_error_and_lockout(env):
    c = env["client"]
    r = c.post("/api/auth/login", json={"email": "nobody@eko.test", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password."


def test_auth_endpoints_are_rate_limited_per_ip(env):
    c = env["client"]
    codes = [c.post("/api/auth/login", json={"email": f"x{i}@eko.test", "password": "nope-nope-1"}).status_code for i in range(12)]
    assert 429 in codes


def test_state_change_requires_csrf_token(env):
    r = sign_in(env)
    c = env["client"]
    assert c.post(PROBE).status_code == 403
    assert c.post(PROBE, headers={"X-CSRF-Token": "forged"}).status_code == 403
    ok = c.post(PROBE, headers={"X-CSRF-Token": r.json()["csrf_token"]})
    assert ok.status_code not in (401, 403), ok.text


def test_viewer_is_read_only_and_operator_cannot_delete(env):
    r = sign_in(env, "view@eko.test")
    c, csrf = env["client"], {"X-CSRF-Token": r.json()["csrf_token"]}
    assert c.get("/api/reconciliation/status").status_code == 200
    assert c.post(PROBE, headers=csrf).status_code == 403
    c.cookies.clear(); sc.rate_limiter.reset()
    r = sign_in(env, "op@eko.test")
    assert c.delete(PROBE, headers={"X-CSRF-Token": r.json()["csrf_token"]}).status_code == 403


def test_logout_revokes_session(env):
    sign_in(env)
    c = env["client"]
    old_cookie = c.cookies.get(sc.SESSION_COOKIE)
    assert c.post("/api/auth/logout").status_code == 200
    c.cookies.set(sc.SESSION_COOKIE, old_cookie)
    assert c.get("/api/reconciliation/status").status_code == 401


def test_idle_session_expires(env):
    sign_in(env)
    db = sqlite3.connect(env["db"]); db.execute("UPDATE auth_sessions SET last_seen=?", (int(time.time()) - sc.SESSION_IDLE_SECONDS - 5,)); db.commit(); db.close()
    assert env["client"].get("/api/reconciliation/status").status_code == 401


def _make_key(env, scopes, revoked=0):
    raw = "eko_" + hashlib.sha256(json.dumps(scopes).encode() + str(revoked).encode()).hexdigest()
    db = sqlite3.connect(env["db"])
    db.execute("INSERT INTO api_keys(id,name,key_hash,organization_id,scopes_json,expires_at,revoked,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (raw[-12:], "agent", hashlib.sha256(raw.encode()).hexdigest(), "eko", json.dumps(scopes), int(time.time()) + 3600, revoked, int(time.time())))
    db.commit(); db.close()
    return {"X-API-Key": raw}


def test_api_key_scopes_are_enforced_and_need_no_csrf(env):
    c = env["client"]
    read = _make_key(env, ["read"])
    assert c.get("/api/reconciliation/status", headers=read).status_code == 200
    assert c.post(PROBE, headers=read).status_code == 403
    full = _make_key(env, ["*"])
    assert c.post(PROBE, headers=full).status_code not in (401, 403)
    revoked = _make_key(env, ["*"], revoked=1)
    assert c.get("/api/reconciliation/status", headers=revoked).status_code == 401
    assert c.get("/api/reconciliation/status", headers={"X-API-Key": "eko_not_a_real_key"}).status_code == 401


def test_token_signed_with_old_hardcoded_secret_is_rejected(env):
    def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    body = b64(json.dumps({"sub": "u-admin", "role": "super_admin", "org": None, "exp": int(time.time()) + 600}).encode())
    sig = b64(hmac.new(b"local-development-only-not-for-hosted-use", body.encode(), hashlib.sha256).digest())
    r = env["client"].get("/api/reconciliation/status", headers={"Authorization": f"Bearer {body}.{sig}"})
    assert r.status_code == 401


def test_state_changes_are_audited(env):
    r = sign_in(env)
    env["client"].post(PROBE, headers={"X-CSRF-Token": r.json()["csrf_token"]})
    rows = sqlite3.connect(env["db"]).execute("SELECT event_type, detail_json FROM audit_events").fetchall()
    events = [e for e, _ in rows]
    assert "auth.login_succeeded" in events and "auth.password_ok_otp_sent" not in events
    assert any(e == "api.request" and PROBE in d for e, d in rows)


def test_lockout_applies_and_a_locked_account_gets_no_session(env):
    c = env["client"]
    for _ in range(5):
        assert c.post("/api/auth/login", json={"email": "admin@eko.test", "password": "wrong-password-123"}).status_code == 401
    sc.rate_limiter.reset()
    assert c.post("/api/auth/login", json={"email": "admin@eko.test", "password": PASSWORD}).status_code == 429
    assert c.get("/api/reconciliation/status").status_code == 401


# ---------------------------------------------------------------------------
# V62.6.215: the SSO (OIDC) button added to the login page needs the config-status
# endpoint reachable before sign-in, and the exchanged bearer token to work for real calls.
# ---------------------------------------------------------------------------

def test_oidc_config_status_is_reachable_before_sign_in_and_hides_the_secret(env):
    # A plain client: no password login, no cookie, no bearer token -- exactly the state
    # of a browser that has just loaded the login page and not signed in yet.
    c = TestClient(app)
    r = c.get("/api/auth/oidc/config-status")
    assert r.status_code == 200, r.text   # was 401 before config-status was added to PUBLIC_PATHS
    body = r.json()
    assert set(body) >= {"configured", "missing_variables", "login_endpoint", "callback_endpoint"}
    assert "OIDC_CLIENT_SECRET" not in json.dumps(body).replace("OIDC_CLIENT_SECRET", "", 1) or body["missing_variables"]
    # The same unauthenticated client is still rejected by every ordinary route.
    assert c.get("/api/auth/session").json()["signed_in"] is False
    assert c.get("/api/reconciliation/status").status_code == 401


def test_sso_signs_in_an_existing_user_with_a_bearer_token_and_no_cookie(env, monkeypatch):
    class _StubOidcClient:
        async def authorize_access_token(self, request):
            return {"userinfo": {"email": "admin@eko.test", "email_verified": True}}
    monkeypatch.setattr(ps, "_get_oidc_client", lambda: _StubOidcClient())
    for var, val in {"OIDC_ISSUER_URL": "https://idp.example.test", "OIDC_CLIENT_ID": "c",
                      "OIDC_CLIENT_SECRET": "s", "OIDC_REDIRECT_URI": "http://127.0.0.1:8000/api/auth/oidc/callback"}.items():
        monkeypatch.setenv(var, val)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/api/auth/oidc/config-status").json()["configured"] is True   # the login page would now show the SSO button

    callback = c.get("/api/auth/oidc/callback")
    assert callback.status_code == 303   # redirect to the frontend with a one-time ?oidc_code=...
    assert "Set-Cookie" not in callback.headers   # SSO issues a bearer token, not the password flow's session cookie
    code = parse_qs(urlparse(callback.headers["location"]).query)["oidc_code"][0]

    exchange = c.post("/api/auth/oidc/exchange", json={"code": code})
    assert exchange.status_code == 200, exchange.text
    token = exchange.json()["access_token"]
    assert c.post("/api/auth/oidc/exchange", json={"code": code}).status_code == 401   # single-use code

    me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "admin@eko.test"
    assert c.get("/api/auth/me").status_code == 401   # the same route rejects the request without the header


def test_sso_rejects_a_verified_identity_with_no_matching_account(env, monkeypatch):
    class _StubOidcClient:
        async def authorize_access_token(self, request):
            return {"userinfo": {"email": "nobody@eko.test", "email_verified": True}}
    monkeypatch.setattr(ps, "_get_oidc_client", lambda: _StubOidcClient())
    for var, val in {"OIDC_ISSUER_URL": "https://idp.example.test", "OIDC_CLIENT_ID": "c",
                      "OIDC_CLIENT_SECRET": "s", "OIDC_REDIRECT_URI": "http://127.0.0.1:8000/api/auth/oidc/callback"}.items():
        monkeypatch.setenv(var, val)
    c = TestClient(app, follow_redirects=False)
    r = c.get("/api/auth/oidc/callback")
    assert r.status_code == 403
    assert "not provisioned" in r.json()["detail"]
