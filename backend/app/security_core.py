"""Security core (V62.6.206): sessions, lockout, rate limits, CSRF and
request authentication/authorization for every /api route.

Login: password -> server-side session (no e-mail code).
The session id lives only in an HttpOnly, SameSite=Strict cookie; state-changing requests
made with that cookie must echo the session's CSRF token in the X-CSRF-Token header.
Machine clients (the super agent) authenticate with an X-API-Key instead.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import platform_security as ps
from app import secret_store
from app.auth_scopes import ADMIN_PATH_PREFIXES, API_SCOPES, SCOPE_ALIASES, effective_scopes  # noqa: F401

log = logging.getLogger("eko.security")
router = APIRouter()

BACKEND_DIR = Path(__file__).resolve().parents[1]
SECRETS_PATH = secret_store.SECRETS_PATH
APP_ENV = os.getenv("APP_ENV", "local").strip().lower()
HOSTED = APP_ENV in {"production", "hosted"}

SESSION_COOKIE = "eko_session"
SESSION_IDLE_SECONDS = max(300, int(os.getenv("SESSION_IDLE_SECONDS", "1800")))
SESSION_ABSOLUTE_SECONDS = max(SESSION_IDLE_SECONDS, int(os.getenv("SESSION_ABSOLUTE_SECONDS", "28800")))
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 900

ROLES = {"super_admin", "org_admin", "operator", "viewer"}


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {
    "/", "/health", "/api/version",
    "/api/auth/status", "/api/auth/session", "/api/auth/login",
    "/api/auth/logout", "/api/auth/oidc/login", "/api/auth/oidc/callback", "/api/auth/oidc/exchange",
    "/api/auth/oidc/config-status",   # the sign-in page needs this, unauthenticated, to decide whether to show an SSO button
}
DOC_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


# ---------------------------------------------------------------------------
# Secrets: environment first, otherwise a per-installation random secret file.
# ---------------------------------------------------------------------------
get_secret = secret_store.get_secret   # see app/secret_store.py (environment first, else a per-installation random value)


def _hmac(value: str) -> str:
    return hmac.new(get_secret("PLATFORM_TOKEN_SECRET").encode(), value.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Schema (portable SQL: works on SQLite and PostgreSQL via platform_security._db)
# ---------------------------------------------------------------------------
def initialize_security_schema():
    conn = ps._db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS auth_sessions (id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL, "
                     "created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, "
                     "ip TEXT, user_agent TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS auth_otp_challenges (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, code_hash TEXT NOT NULL, "
                     "expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, consumed INTEGER NOT NULL DEFAULT 0, "
                     "created_at INTEGER NOT NULL, ip TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS auth_login_throttle (email TEXT PRIMARY KEY, failed_count INTEGER NOT NULL DEFAULT 0, "
                     "locked_until INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL)")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# In-memory sliding-window rate limiter (per process)
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self):
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
AUTH_RATE = (10, 300)      # 10 auth attempts per 5 minutes per client IP
API_RATE = (1200, 60)      # 1200 API calls per minute per client


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce_auth_rate(request: Request):
    if not rate_limiter.allow(f"auth:{client_ip(request)}", *AUTH_RATE):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Please wait a few minutes and try again.")





# ---------------------------------------------------------------------------
# Lockout (per e-mail, applied whether or not the account exists: no enumeration)
# ---------------------------------------------------------------------------
def _throttle_row(conn, email):
    return conn.execute("SELECT failed_count, locked_until FROM auth_login_throttle WHERE email=?", (email,)).fetchone()


def _check_locked(conn, email, now):
    row = _throttle_row(conn, email)
    if row and int(row["locked_until"]) > now:
        minutes = max(1, (int(row["locked_until"]) - now + 59) // 60)
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {minutes} minute(s).")


def _record_failure(conn, email, now):
    row = _throttle_row(conn, email)
    count = (int(row["failed_count"]) if row else 0) + 1
    locked_until = now + LOCKOUT_SECONDS if count >= LOCKOUT_THRESHOLD else 0
    if row:
        conn.execute("UPDATE auth_login_throttle SET failed_count=?, locked_until=?, updated_at=? WHERE email=?",
                     (0 if locked_until else count, locked_until, now, email))
    else:
        conn.execute("INSERT INTO auth_login_throttle(email, failed_count, locked_until, updated_at) VALUES(?,?,?,?)",
                     (email, count, locked_until, now))
    return locked_until


def _clear_failures(conn, email):
    conn.execute("DELETE FROM auth_login_throttle WHERE email=?", (email,))


def _audit(conn, user_id, org_id, event, detail):
    conn.execute("INSERT INTO audit_events(actor_user_id,organization_id,event_type,detail_json,created_at) VALUES(?,?,?,?,?)",
                 (user_id, org_id, event, json.dumps(detail, default=str), int(time.time())))


# ---------------------------------------------------------------------------
# Login endpoints
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


_DUMMY_HASH = ps._password_hash(secrets.token_urlsafe(16))


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    """Verify the password and open a server-side session (lockout and rate limits apply)."""
    _enforce_auth_rate(request)
    email, now = body.email.strip().lower(), int(time.time())
    conn = ps._db()
    try:
        _check_locked(conn, email, now)
        user = conn.execute("SELECT * FROM users WHERE lower(email)=? AND active=1", (email,)).fetchone()
        password_ok = ps._verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH)
        if not user or not password_ok:
            locked_until = _record_failure(conn, email, now)
            _audit(conn, user["id"] if user else None, user["organization_id"] if user else None, "auth.login_failed",
                   {"email": email, "ip": client_ip(request), "locked": bool(locked_until)})
            conn.commit()
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        _clear_failures(conn, email)
        session_id, csrf = _open_session(conn, user, request, now)
        _audit(conn, user["id"], user["organization_id"], "auth.login_succeeded", {"ip": client_ip(request)})
        conn.commit()
    finally:
        conn.close()
    _set_session_cookie(response, session_id, request)
    return {"user": _public_user(user), "csrf_token": csrf, "idle_timeout_seconds": SESSION_IDLE_SECONDS}


def _cookie_secure(request: Request) -> bool:
    return HOSTED or request.url.scheme == "https"


def _open_session(conn, user, request: Request, now: int):
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    conn.execute("INSERT INTO auth_sessions(id_hash,user_id,csrf_token,created_at,last_seen,expires_at,revoked,ip,user_agent) "
                 "VALUES(?,?,?,?,?,?,0,?,?)",
                 (_hmac(f"session:{session_id}"), user["id"], csrf, now, now, now + SESSION_ABSOLUTE_SECONDS,
                  client_ip(request), request.headers.get("user-agent", "")[:300]))
    return session_id, csrf


def _set_session_cookie(response: Response, session_id: str, request: Request):
    response.set_cookie(SESSION_COOKIE, session_id, max_age=SESSION_ABSOLUTE_SECONDS, httponly=True,
                        secure=_cookie_secure(request), samesite="strict", path="/")


@router.post("/logout")
def logout(request: Request, response: Response):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        conn = ps._db()
        try:
            conn.execute("UPDATE auth_sessions SET revoked=1 WHERE id_hash=?", (_hmac(f"session:{session_id}"),))
            conn.commit()
        finally:
            conn.close()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"signed_out": True}


@router.get("/session")
def session_info(request: Request):
    # Public status question asked on every page load: answer 200 with signed_in=false rather
    # than a 401 that looks like an error in the server log. No data is returned when signed out.
    principal = getattr(request.state, "principal", None) or authenticate_request(request)
    if not principal:
        return {"signed_in": False}
    return {"signed_in": True, "user": {k: principal.get(k) for k in ("sub", "email", "role", "org")}, "via": principal.get("via"),
            "csrf_token": principal.get("csrf"), "idle_timeout_seconds": SESSION_IDLE_SECONDS}


def _public_user(user) -> dict:
    return {"sub": user["id"], "email": user["email"], "role": user["role"], "org": user["organization_id"]}


# ---------------------------------------------------------------------------
# Request authentication / authorization (used by the middleware in main.py)
# ---------------------------------------------------------------------------
def _session_principal(session_id: str) -> dict | None:
    now = int(time.time())
    conn = ps._db()
    try:
        row = conn.execute("SELECT s.*, u.email, u.role, u.organization_id, u.active FROM auth_sessions s JOIN users u ON u.id=s.user_id "
                           "WHERE s.id_hash=?", (_hmac(f"session:{session_id}"),)).fetchone()
        if (not row or int(row["revoked"]) or not int(row["active"]) or int(row["expires_at"]) <= now
                or now - int(row["last_seen"]) > SESSION_IDLE_SECONDS):
            return None
        if now - int(row["last_seen"]) > 60:
            try:
                conn.execute("UPDATE auth_sessions SET last_seen=? WHERE id_hash=?", (now, row["id_hash"]))
                conn.commit()
            except Exception:
                conn.rollback()   # a busy database must not sign the user out; the refresh is retried on the next request
        return {"sub": row["user_id"], "email": row["email"], "role": row["role"], "org": row["organization_id"],
                "csrf": row["csrf_token"], "via": "session"}
    finally:
        conn.close()


def _api_key_principal(raw_key: str) -> dict | None:
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    conn = ps._db()
    try:
        row = conn.execute("SELECT * FROM api_keys WHERE key_hash=?", (digest,)).fetchone()
        if not row or int(row["revoked"]) or int(row["expires_at"]) <= int(time.time()):
            return None
        scopes = effective_scopes(json.loads(row["scopes_json"]))
        # "*" keys act as super_admin and "admin" keys as org_admin of their organisation, so the
        # existing role checks on user/key management apply to agents unchanged.
        role = "super_admin" if "*" in scopes else "org_admin" if "admin" in scopes else "agent"
        return {"sub": f"api_key:{row['id']}", "email": f"api-key:{row['name']}", "role": role, "org": row["organization_id"],
                "scopes": sorted(scopes), "via": "api_key"}
    finally:
        conn.close()


def authenticate_request(request: Request) -> dict | None:
    """Return the caller's principal, or None when the request is not authenticated."""
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return _api_key_principal(api_key)
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        principal = _session_principal(session_id)
        if principal:
            return principal
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            claims = ps.verify_token(header.split(None, 1)[1].strip())
        except HTTPException:
            return None
        return {"sub": claims["sub"], "email": claims.get("email"), "role": claims["role"], "org": claims.get("org"), "via": "bearer"}
    return None


def authorization_error(principal: dict, method: str, path: str) -> str | None:
    """Return a reason string when the principal may not perform this request."""
    if principal.get("via") == "api_key":
        scopes = effective_scopes(principal.get("scopes"))
        if "*" in scopes:
            return None
        needed = "admin" if path.startswith(ADMIN_PATH_PREFIXES) else ("read" if method in SAFE_METHODS else "write")
        if needed in scopes or (needed == "read" and scopes & {"write", "admin"}):
            return None
        return f"API key lacks the '{needed}' scope."
    role = principal.get("role")
    if role not in ROLES:
        return "Unknown role."
    if method in SAFE_METHODS or role in {"super_admin", "org_admin"}:
        return None
    if role == "viewer":
        return "Viewer accounts are read-only."
    if method == "DELETE":
        return "Only administrators may delete data."
    return None


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or (not HOSTED and path in DOC_PATHS) or not path.startswith(("/api/", "/docs", "/redoc", "/openapi"))
