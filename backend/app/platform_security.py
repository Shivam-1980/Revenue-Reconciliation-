"""Platform identity: users, organisations, roles, API keys and OIDC.

Password login and sessions live in app.security_core (V62.6.206).

The legacy local reconciliation workflow remains unchanged by default. Hosted mode is
fail-closed for legacy file-backed business routes until tenant-scoped storage migration
is enabled; this prevents falsely advertising shared-file data as tenant isolated.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, sqlite3, time
from app.db_compat import connect_platform, initialize_sqlite_schema, integrity_errors, USE_POSTGRES
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("PLATFORM_DB_PATH", str(BACKEND_DIR / "data" / "platform.sqlite3")))
TOKEN_SECRET = os.getenv("PLATFORM_TOKEN_SECRET", "")
TOKEN_TTL_SECONDS = max(300, int(os.getenv("PLATFORM_TOKEN_TTL_SECONDS", "3600")))
AUTH_MODE = os.getenv("PLATFORM_AUTH_MODE", "local").strip().lower()


def _db():
    if USE_POSTGRES:
        return connect_platform()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    initialize_sqlite_schema(conn)
    return conn


def initialize_platform_db():
    conn = _db()
    try:
        if not USE_POSTGRES:
            conn.execute("CREATE TABLE IF NOT EXISTS oidc_login_codes (code_hash TEXT PRIMARY KEY, access_token TEXT NOT NULL, expires_at INTEGER NOT NULL)")
            conn.commit()
    finally:
        conn.close()


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _password_hash(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256${_b64e(salt)}${_b64e(digest)}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$", 2)
        if algorithm != "pbkdf2_sha256": return False
        actual = _password_hash(password, _b64d(salt)).split("$", 2)[2]
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _signing_secret() -> bytes:
    # Environment secret, or a random per-installation secret (never a hardcoded default).
    from app.security_core import get_secret
    try:
        return get_secret("PLATFORM_TOKEN_SECRET").encode()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _issue_token(user: sqlite3.Row) -> str:
    now = int(time.time())
    payload = {"sub": user["id"], "email": user["email"], "role": user["role"],
               "org": user["organization_id"], "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_signing_secret(), body.encode(), hashlib.sha256).digest())
    return body + "." + sig


def verify_token(token: str) -> dict:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(_signing_secret(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(signature)):
            raise ValueError("bad signature")
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise ValueError("expired")
        if payload.get("role") not in {"super_admin", "org_admin", "operator", "viewer"}:
            raise ValueError("invalid role")
        return payload
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token.")


def current_user(request: Request) -> dict:
    """Principal resolved by the auth middleware (session cookie, API key or bearer token)."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        from app.security_core import authenticate_request
        principal = authenticate_request(request)
    if not principal:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    return principal


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


@router.get("/status")
def platform_status():
    """Expose capability status without revealing secrets or user records."""
    return {"auth_mode": AUTH_MODE, "two_factor": "none",
            "database": "postgresql" if USE_POSTGRES else "sqlite_local_or_metadata", "tenant_isolation": "not_ready_for_hosted_business_routes"}


@router.get("/me")
def me(request: Request):
    claims = current_user(request)
    conn = _db()
    try:
        row = conn.execute("SELECT id,email,role,organization_id,active FROM users WHERE id=?", (claims["sub"],)).fetchone()
        if not row or not row["active"]:
            raise HTTPException(status_code=401, detail="User is inactive or no longer exists.")
        return dict(row)
    finally:
        conn.close()


@router.get("/workspaces")
def workspaces(request: Request):
    claims = current_user(request)
    conn = _db()
    try:
        if claims["role"] == "super_admin":
            rows = conn.execute("SELECT id,name,created_at,active FROM organizations ORDER BY name").fetchall()
        elif claims.get("org"):
            rows = conn.execute("SELECT id,name,created_at,active FROM organizations WHERE id=? AND active=1", (claims["org"],)).fetchall()
        else:
            rows = []
        return {"items": [dict(r) for r in rows]}
    finally:
        conn.close()


def record_audit(actor: dict, event_type: str, detail: dict):
    conn = _db()
    try:
        conn.execute("INSERT INTO audit_events(actor_user_id,organization_id,event_type,detail_json,created_at) VALUES(?,?,?,?,?)",
                     (actor.get("sub"), actor.get("org"), event_type, json.dumps(detail, default=str), int(time.time())))
        conn.commit()
    finally:
        conn.close()

# Additive administration and scoped API-key support. Existing local business routes
# remain untouched; hosted routes stay fail-closed until tenant storage is migrated.
from fastapi import Depends

class OrganizationCreate(BaseModel):
    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=2, max_length=160)

class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=14, max_length=256)
    role: str = Field(pattern=r"^(org_admin|operator|viewer)$")
    organization_id: str = Field(min_length=2, max_length=64)

class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    scopes: list[str] = Field(min_length=1, max_length=20)
    organization_id: str = Field(min_length=2, max_length=64)
    expires_in_days: int = Field(default=90, ge=1, le=365)

from app.auth_scopes import API_SCOPES, SCOPE_ALIASES  # noqa: E402  (scope vocabulary shared with the auth middleware)
_ALLOWED_SCOPES = API_SCOPES | set(SCOPE_ALIASES)

def require_roles(*roles):
    def dependency(request: Request):
        actor = current_user(request)
        if actor.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation.")
        return actor
    return dependency

@router.post("/organizations", status_code=201)
def create_organization(body: OrganizationCreate, actor=Depends(require_roles("super_admin"))):
    conn = _db()
    try:
        now = int(time.time())
        try:
            conn.execute("INSERT INTO organizations(id,name,created_at,active) VALUES(?,?,?,1)", (body.id, body.name.strip(), now))
            conn.commit()
        except integrity_errors():
            raise HTTPException(status_code=409, detail="Organization ID already exists.")
        record_audit(actor, "organization.created", {"organization_id": body.id})
        return {"id": body.id, "name": body.name.strip(), "active": True}
    finally:
        conn.close()

@router.post("/users", status_code=201)
def create_user(body: UserCreate, actor=Depends(require_roles("super_admin", "org_admin"))):
    org_id = body.organization_id
    if actor.get("role") != "super_admin" and actor.get("org") != org_id:
        raise HTTPException(status_code=403, detail="Organisation administrators can only manage their own organisation.")
    conn = _db()
    try:
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND active=1", (org_id,)).fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="Active organisation not found.")
        user_id = secrets.token_hex(16)
        try:
            conn.execute("INSERT INTO users(id,email,password_hash,role,organization_id,active,created_at) VALUES(?,?,?,?,?,1,?)",
                         (user_id, body.email.strip().lower(), _password_hash(body.password), body.role, org_id, int(time.time())))
            conn.commit()
        except integrity_errors():
            raise HTTPException(status_code=409, detail="Email already exists.")
        record_audit(actor, "user.created", {"user_id": user_id, "role": body.role, "organization_id": org_id})
        return {"id": user_id, "email": body.email.strip().lower(), "role": body.role, "organization_id": org_id, "active": True}
    finally:
        conn.close()

@router.get("/users")
def list_users(request: Request, organization_id: Optional[str] = None):
    actor = current_user(request)
    if actor.get("role") not in {"super_admin", "org_admin"}:
        raise HTTPException(status_code=403, detail="User administration role required.")
    org_id = organization_id or actor.get("org")
    if actor.get("role") != "super_admin" and org_id != actor.get("org"):
        raise HTTPException(status_code=403, detail="Cross-organisation access denied.")
    conn = _db()
    try:
        rows = conn.execute("SELECT id,email,role,organization_id,active,created_at FROM users WHERE organization_id=? ORDER BY email", (org_id,)).fetchall()
        return {"items": [dict(r) for r in rows]}
    finally:
        conn.close()

@router.post("/api-keys", status_code=201)
def create_api_key(body: ApiKeyCreate, actor=Depends(require_roles("super_admin", "org_admin"))):
    if actor.get("role") != "super_admin" and actor.get("org") != body.organization_id:
        raise HTTPException(status_code=403, detail="Cross-organisation API key creation denied.")
    scopes = sorted(set(body.scopes))
    if not scopes or not set(scopes).issubset(_ALLOWED_SCOPES):
        raise HTTPException(status_code=422, detail={"allowed_scopes": sorted(_ALLOWED_SCOPES)})
    raw = "eko_" + secrets.token_urlsafe(32)
    key_id = secrets.token_hex(12)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    conn = _db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, organization_id TEXT NOT NULL, scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, FOREIGN KEY(organization_id) REFERENCES organizations(id))")
        conn.execute("INSERT INTO api_keys(id,name,key_hash,organization_id,scopes_json,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
                     (key_id, body.name.strip(), digest, body.organization_id, json.dumps(scopes), int(time.time()) + body.expires_in_days*86400, int(time.time())))
        conn.commit()
        record_audit(actor, "api_key.created", {"key_id": key_id, "organization_id": body.organization_id, "scopes": scopes})
        return {"id": key_id, "name": body.name.strip(), "organization_id": body.organization_id, "scopes": scopes,
                "expires_in_days": body.expires_in_days, "api_key": raw, "warning": "Copy this key now; it will not be shown again."}
    finally:
        conn.close()

@router.get("/api-keys")
def list_api_keys(request: Request, organization_id: Optional[str] = None):
    """List API keys (never the key itself or its hash)."""
    actor = current_user(request)
    if actor.get("role") not in {"super_admin", "org_admin"}:
        raise HTTPException(status_code=403, detail="API key administration role required.")
    org_id = organization_id or actor.get("org")
    if actor.get("role") != "super_admin" and org_id != actor.get("org"):
        raise HTTPException(status_code=403, detail="Cross-organisation access denied.")
    conn = _db()
    try:
        sql = "SELECT id,name,organization_id,scopes_json,expires_at,revoked,created_at FROM api_keys"
        rows = conn.execute(sql + (" WHERE organization_id=? ORDER BY created_at DESC" if org_id else " ORDER BY created_at DESC"),
                            (org_id,) if org_id else ()).fetchall()
        now = int(time.time())
        return {"items": [{"id": r["id"], "name": r["name"], "organization_id": r["organization_id"], "scopes": json.loads(r["scopes_json"]),
                           "expires_at": int(r["expires_at"]), "revoked": bool(r["revoked"]),
                           "active": not r["revoked"] and int(r["expires_at"]) > now, "created_at": int(r["created_at"])} for r in rows]}
    finally:
        conn.close()


@router.post("/api-keys/{key_id}/revoke")
def revoke_api_key(key_id: str, request: Request):
    actor = current_user(request)
    if actor.get("role") not in {"super_admin", "org_admin"}:
        raise HTTPException(status_code=403, detail="API key administration role required.")
    conn = _db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, organization_id TEXT NOT NULL, scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, FOREIGN KEY(organization_id) REFERENCES organizations(id))")
        row = conn.execute("SELECT organization_id FROM api_keys WHERE id=?", (key_id,)).fetchone()
        if not row: raise HTTPException(status_code=404, detail="API key not found.")
        if actor.get("role") != "super_admin" and actor.get("org") != row["organization_id"]:
            raise HTTPException(status_code=403, detail="Cross-organisation API key revocation denied.")
        conn.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (key_id,)); conn.commit()
        record_audit(actor, "api_key.revoked", {"key_id": key_id})
        return {"id": key_id, "revoked": True}
    finally: conn.close()

@router.get("/oidc/config-status")
def oidc_config_status():
    """Report OIDC configuration readiness; never expose client secrets."""
    required = ["OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"]
    missing = [name for name in required if not os.getenv(name)]
    issuer = (os.getenv("OIDC_ISSUER_URL") or "").lower()
    # A display hint only, for the sign-in button label/icon; never used for anything security-relevant
    # (the real identity check is the provider's own signed token, verified in oidc_callback).
    provider = "google" if "accounts.google.com" in issuer else "microsoft" if "microsoftonline.com" in issuer else "sso"
    return {"configured": not missing, "missing_variables": missing, "two_factor": "none", "provider": provider,
            "login_endpoint": "/api/auth/oidc/login", "callback_endpoint": "/api/auth/oidc/callback",
            "account_policy": "OIDC identities must map to an active pre-provisioned platform user."}

# OIDC Authorization Code flow. Authlib validates the ID token (issuer, audience,
# signature, expiry and nonce); only pre-provisioned active accounts may enter.
_oidc_client = None

def _get_oidc_client():
    global _oidc_client
    if _oidc_client is not None:
        return _oidc_client
    required = ["OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise HTTPException(status_code=503, detail={"message": "OIDC is not configured.", "missing_variables": missing})
    try:
        from authlib.integrations.starlette_client import OAuth
    except ImportError:
        raise HTTPException(status_code=503, detail="OIDC dependency is not installed. Install backend requirements before enabling OIDC.")
    oauth = OAuth()
    oauth.register(name="eko_oidc", server_metadata_url=os.environ["OIDC_ISSUER_URL"].rstrip("/") + "/.well-known/openid-configuration",
                   client_id=os.environ["OIDC_CLIENT_ID"], client_secret=os.environ["OIDC_CLIENT_SECRET"],
                   client_kwargs={"scope": os.getenv("OIDC_SCOPES", "openid email profile")})
    _oidc_client = oauth.eko_oidc
    return _oidc_client

@router.get("/oidc/login")
async def oidc_login(request: Request):
    """Start OIDC login; redirect URI must exactly match provider configuration."""
    client = _get_oidc_client()
    redirect_uri = os.environ["OIDC_REDIRECT_URI"]
    return await client.authorize_redirect(request, redirect_uri, prompt=os.getenv("OIDC_PROMPT", "select_account"))

@router.get("/oidc/callback")
async def oidc_callback(request: Request):
    """Validate provider response and map its verified email to a pre-provisioned user."""
    client = _get_oidc_client()
    try:
        token = await client.authorize_access_token(request)
        userinfo = token.get("userinfo") or await client.userinfo(token=token)
    except Exception:
        raise HTTPException(status_code=401, detail="OIDC login failed token/state/issuer validation.")
    email = str(userinfo.get("email", "")).strip().lower()
    if not email or userinfo.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="OIDC provider must return a verified email address.")
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM users WHERE lower(email)=lower(?) AND active=1", (email,)).fetchone()
        if not row:
            conn.execute("INSERT INTO audit_events(actor_user_id,organization_id,event_type,detail_json,created_at) VALUES(NULL,NULL,'auth.oidc_unprovisioned',?,?)",
                         (json.dumps({"email": email}), int(time.time())))
            conn.commit()
            raise HTTPException(status_code=403, detail="This verified OIDC identity is not provisioned. Ask a platform administrator to create the account.")
        conn.execute("INSERT INTO audit_events(actor_user_id,organization_id,event_type,detail_json,created_at) VALUES(?,?, 'auth.oidc_login_succeeded', '{}', ?)",
                     (row["id"], row["organization_id"], int(time.time())))
        conn.commit()
        access_token = _issue_token(row)
    finally:
        conn.close()
    # Avoid placing bearer tokens in URLs. Frontend exchanges a short-lived, one-time code.
    code = secrets.token_urlsafe(32)
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    conn = _db()
    try:
        conn.execute("INSERT INTO oidc_login_codes(code_hash,access_token,expires_at) VALUES(?,?,?)", (code_hash, access_token, int(time.time()) + 60))
        conn.commit()
    finally:
        conn.close()
    frontend_url = os.getenv("OIDC_FRONTEND_SUCCESS_URL", "http://127.0.0.1:5173/")
    from urllib.parse import urlencode
    from fastapi.responses import RedirectResponse
    return RedirectResponse(frontend_url + "?" + urlencode({"oidc_code": code}), status_code=303)

class OIDCExchangeRequest(BaseModel):
    code: str = Field(min_length=20, max_length=256)

@router.post("/oidc/exchange")
def oidc_exchange(body: OIDCExchangeRequest):
    """Exchange one-time callback code for an app token; code is single-use and expires in 60s."""
    digest = hashlib.sha256(body.code.encode()).hexdigest()
    conn = _db()
    try:
        # Serialize redemption so the same short-lived code cannot be exchanged twice
        # under concurrent requests. PostgreSQL locks the selected row; SQLite obtains
        # a write reservation before reading.
        if USE_POSTGRES:
            conn.execute("BEGIN")
            record = conn.execute("SELECT access_token,expires_at FROM oidc_login_codes WHERE code_hash=? FOR UPDATE", (digest,)).fetchone()
        else:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute("SELECT access_token,expires_at FROM oidc_login_codes WHERE code_hash=?", (digest,)).fetchone()
        if record:
            conn.execute("DELETE FROM oidc_login_codes WHERE code_hash=?", (digest,))
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
        raise
    finally:
        conn.close()
    if not record or int(record["expires_at"]) <= int(time.time()):
        raise HTTPException(status_code=401, detail="OIDC exchange code is invalid, expired or already used.")
    return {"access_token": record["access_token"], "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS}

def verify_scoped_api_key(raw_key: str, required_scope: str, organization_id: str | None = None) -> dict:
    """Validate an issued API key and enforce scope + tenant binding for agent adapters."""
    if not raw_key or not raw_key.startswith("eko_"):
        raise HTTPException(status_code=401, detail="Valid scoped API key required.")
    digest = hashlib.sha256(raw_key.encode()).hexdigest()
    conn = _db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS api_keys (id TEXT PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, organization_id TEXT NOT NULL, scopes_json TEXT NOT NULL, expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, FOREIGN KEY(organization_id) REFERENCES organizations(id))")
        row = conn.execute("SELECT * FROM api_keys WHERE key_hash=?", (digest,)).fetchone()
        if not row or row["revoked"] or row["expires_at"] <= int(time.time()):
            raise HTTPException(status_code=401, detail="API key is invalid, revoked, or expired.")
        scopes = json.loads(row["scopes_json"])
        if required_scope not in scopes:
            raise HTTPException(status_code=403, detail="API key does not have the required scope.")
        if organization_id and organization_id != row["organization_id"]:
            raise HTTPException(status_code=403, detail="API key is not authorised for this organisation.")
        return {"key_id": row["id"], "organization_id": row["organization_id"], "scopes": scopes}
    finally:
        conn.close()
