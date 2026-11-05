
import logging
import os
import json
import math
from datetime import date, datetime
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
import hmac
from app.api import upload
from app.api import source_data,reconciliation,dashboard,processing,audit,operational,ai_harness,platform_jobs,agent_gateway,tenant_business,reconciliation_history
from app import platform_security, security_core, database
from app.api import database_api, agent_v1
from app.services import db_sync


def _strict_json_safe(value):
    """Convert NaN/Infinity and numpy/pandas scalar values before API JSON serialization."""
    try:
        import pandas as pd
        import numpy as np
        if value is pd.NA or value is pd.NaT:
            return None
        if isinstance(value, (np.bool_,)):
            return bool(value)
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating, float)):
            number = float(value)
            return number if math.isfinite(number) else None
        if isinstance(value, np.ndarray):
            return [_strict_json_safe(v) for v in value.tolist()]
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return value.isoformat()
    except ImportError:
        if isinstance(value, float):
            return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _strict_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_strict_json_safe(v) for v in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except (ImportError, TypeError, ValueError):
        pass
    if hasattr(value, 'item'):
        try:
            return _strict_json_safe(value.item())
        except (ValueError, TypeError):
            pass
    return value


class StrictJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(_strict_json_safe(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


# Compatibility marker retained for workspace-reset contract tests: 62.6.184-platform-foundation-plus; superseded by 62.6.188-authenticated-workspace-hardening.
# 62.6.188-authenticated-workspace-hardening
APP_ENV = os.getenv("APP_ENV", "local").strip().lower()
if APP_ENV in {"production", "hosted"} and not os.getenv("PLATFORM_SESSION_SECRET"):
    raise RuntimeError("PLATFORM_SESSION_SECRET must be set in hosted/production mode; refusing to start with a default session key.")
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "50")))

class RequestSafetyMiddleware(BaseHTTPMiddleware):
    """Apply request-size and baseline browser security controls without changing local API contracts."""
    async def dispatch(self, request: Request, call_next):
        if APP_ENV in {"production", "hosted"} and request.url.path != "/health":
            # Hosted mode serves HTTPS only. Behind a TLS proxy (EKO_BEHIND_PROXY=true) its X-Forwarded-Proto is trusted.
            proto = request.url.scheme
            if os.getenv("EKO_BEHIND_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}:
                proto = request.headers.get("x-forwarded-proto", proto).split(",")[0].strip().lower()
            if proto != "https":
                if request.url.path.startswith("/api/"):
                    return JSONResponse(status_code=400, content={"detail": "HTTPS is required."})
                return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_UPLOAD_MB * 1024 * 1024:
                    return JSONResponse(status_code=413, content={"detail": f"Request exceeds the configured {MAX_UPLOAD_MB} MB limit."})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store" if request.url.path.startswith("/api/") else "no-cache")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.startswith("/api/"):
            # API responses are data only; they must never be rendered or framed as documents.
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class AuthEnforcementMiddleware(BaseHTTPMiddleware):
    """Every /api route requires a signed-in session (password) or an API key.

    Cookie sessions must send the session CSRF token on state-changing requests. Roles and
    API-key scopes are enforced here; every state-changing request is written to the audit log.
    """
    async def dispatch(self, request: Request, call_next):
        path, method = request.url.path, request.method
        if method == "OPTIONS" or security_core.is_public(path):
            return await call_next(request)
        principal = await run_in_threadpool(security_core.authenticate_request, request)
        if not principal:
            return JSONResponse(status_code=401, content={"detail": "Sign-in required."})
        if not security_core.rate_limiter.allow(f"api:{principal['sub']}", *security_core.API_RATE):
            return JSONResponse(status_code=429, content={"detail": "Too many requests. Please slow down."})
        if principal.get("via") == "session" and method not in security_core.SAFE_METHODS:
            sent = request.headers.get("x-csrf-token", "")
            if not sent or not hmac.compare_digest(sent, principal.get("csrf") or ""):
                return JSONResponse(status_code=403, content={"detail": "Security check failed (CSRF). Refresh the page and try again."})
        reason = security_core.authorization_error(principal, method, path)
        if reason:
            return JSONResponse(status_code=403, content={"detail": reason})
        request.state.principal = principal
        try:
            response = await call_next(request)
        except Exception as exc:
            # An unhandled error would leave the middleware stack without CORS headers, and the browser would
            # report it as "backend not responding". Answer with a normal JSON error instead (V62.6.213).
            logging.getLogger("eko.api").exception("Unhandled error in %s %s", method, path)
            return JSONResponse(status_code=500, content={"detail": f"The server hit an unexpected error ({type(exc).__name__}). Details are in backend_runtime.log."})
        if method not in security_core.SAFE_METHODS:
            try:
                await run_in_threadpool(platform_security.record_audit, principal, "api.request",
                                        {"method": method, "path": path, "status": response.status_code, "via": principal.get("via")})
            except Exception:
                # The audit entry is best effort at this point: the action itself already succeeded.
                logging.getLogger("eko.api").exception("Could not write audit entry for %s %s", method, path)
            if 200 <= response.status_code < 300 and path.startswith(DB_SYNC_TRIGGERS):
                db_sync.sync_in_background(principal.get("email") or principal.get("sub"), f"{method} {path}")
        return response


# Successful calls to these routes change the workspace; the database is synced afterwards.
DB_SYNC_TRIGGERS = ("/api/upload/", "/api/reconciliation/run", "/api/reconciliation/history/", "/api/workspace/")  # /api/agent/v1/sync is synchronous

app=FastAPI(docs_url=None if APP_ENV in {"production", "hosted"} else "/docs", redoc_url=None, openapi_url=None if APP_ENV in {"production", "hosted"} else "/openapi.json", title="Revenue Reconciliation API",version="62.6.216-ui-security-speed",default_response_class=StrictJSONResponse)
platform_security.initialize_platform_db()
database.init_schema()
security_core.initialize_security_schema()
# Record what is in the workspace now (e.g. retire uploads cleared by the startup reset).
db_sync.sync_in_background("system", "startup")


def _protect_data_at_startup():
    """Encrypt older saved months and mask personal identifiers in older rows (once; safe to repeat)."""
    import threading
    def work():
        log = logging.getLogger("eko.privacy")
        try:
            from app.services import period_store, privacy
            n = period_store.encrypt_legacy_archives()
            if n: log.warning("Encrypted %d saved month(s) that were stored unencrypted", n)
            privacy.mask_existing_rows()
            from app import xlsx_scan
            if xlsx_scan.parallel_available(1 << 62):
                xlsx_scan.warm_pool()                          # first big upload starts without waiting for the worker processes
            from app.services import backup
            backup.auto_backup_if_due(24, "automatic-daily")      # at most one automatic backup per day at start
        except Exception:
            log.exception("Startup data protection failed (will retry on the next start)")
    threading.Thread(target=work, name="eko-data-protection", daemon=True).start()


_protect_data_at_startup()
origins=os.getenv("CORS_ORIGINS","http://localhost:5173,http://127.0.0.1:5173").split(",")
# Keep localhost convenience only in local mode. Hosted deployments must enumerate exact trusted origins.
local_origin_regex = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$" if APP_ENV in {"local", "development", "dev"} else None
app.add_middleware(SessionMiddleware, secret_key=security_core.get_secret("PLATFORM_SESSION_SECRET"), same_site="lax", https_only=APP_ENV in {"production", "hosted"}, max_age=600)
app.add_middleware(AuthEnforcementMiddleware)
app.add_middleware(RequestSafetyMiddleware)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in origins if x.strip()],allow_origin_regex=local_origin_regex,allow_credentials=True,allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Request-ID", "X-Eko-Workspace", "X-CSRF-Token", "X-API-Key"])
app.include_router(security_core.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(database_api.router, prefix="/api/database", tags=["Database"])
app.include_router(agent_v1.router, prefix="/api/agent/v1", tags=["Agent API v1"])
app.include_router(platform_security.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(platform_jobs.router, prefix="/api/platform/jobs", tags=["Background Jobs"])
app.include_router(tenant_business.router, prefix="/api/tenant-workspace", tags=["Tenant Workspace"])
app.include_router(agent_gateway.router, prefix="/api/agent", tags=["Scoped Agent API"])
app.include_router(source_data.router, prefix="/api/source-data", tags=["source-data"])
app.include_router(upload.router,prefix="/api/upload",tags=["File Upload"]); app.include_router(reconciliation.router,prefix="/api/reconciliation",tags=["Reconciliation"]); app.include_router(reconciliation_history.router,prefix="/api/reconciliation/history",tags=["Monthly Reconciliation History"]); app.include_router(dashboard.router,prefix="/api/dashboard",tags=["Dashboard"]); app.include_router(processing.router,prefix="/api/processing",tags=["Processing"]); app.include_router(audit.router,prefix="/api/audit",tags=["Audit & Controls"]); app.include_router(operational.router,prefix="/api/operational",tags=["Operational Controls"]); app.include_router(ai_harness.router,prefix="/api/ai-harness",tags=["AI Harness"])
@app.middleware("http")
async def hosted_mode_guard(request: Request, call_next):
    """Fail closed for hosted mode until file-backed business data is tenant-scoped.

    Local mode preserves the existing single-user workflow. In hosted mode, authentication
    endpoints remain available, but legacy business routes are blocked rather than exposing
    shared on-disk data across organisations.
    """
    if APP_ENV in {"production", "hosted"} and request.url.path.startswith("/api/"):
        # These platform routes enforce their own bearer-token, role, scope and tenant checks.
        # Legacy file-backed business endpoints remain blocked until their storage is tenant-scoped.
        allowed = (request.url.path in {"/api/version", "/health"}
                   or request.url.path.startswith("/api/auth/")
                   or request.url.path.startswith("/api/tenant-workspace/")
                   or request.url.path.startswith("/api/platform/jobs/")
                   or request.url.path.startswith("/api/agent/"))
        if not allowed and request.method != "OPTIONS":
            return JSONResponse(status_code=503, content={"detail": "Hosted business routes are disabled until tenant-scoped storage and authorization migration is complete. Run with APP_ENV=local only for the existing single-user desktop workflow."})
    return await call_next(request)

@app.get("/")
def root(): return {"message":"Revenue Reconciliation API is running","docs":"/docs"}
@app.get("/health")
def health(): return {"status":"healthy"}

@app.post("/api/workspace/clear-current-data")
def clear_current_workspace_data(request: Request):
    """Clear the local current-period workspace; refuse remote destructive requests.

    The current release is a single-user local workflow. A hosted/multi-user deployment
    must replace this with authenticated workspace-scoped deletion before enabling it.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Workspace reset is restricted to the local operator until authenticated workspace-scoped reset is enabled.")
    try:
        import runpy
        reset_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reset_initial_data.py"))
        # run_path does not execute main when run_name is not __main__; invoke it explicitly.
        namespace = runpy.run_path(reset_script, run_name="workspace_reset_module")
        namespace["main"]()
        return {"status": "cleared", "message": "Current-period uploads and generated results cleared; permanent SBI rules preserved."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not clear current workspace data: {exc}")

@app.get("/api/version")
def version(): return {"version":"62.6.216-ui-security-speed","source":"current-uploaded-files","ai_harness":"2.0.0-phase2-investigation-agent","platform_auth":"sqlite_local_or_postgres_metadata","platform_jobs":"durable_queue_foundation","two_factor":"none"}
