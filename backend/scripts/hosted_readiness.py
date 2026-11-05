"""Read-only hosted deployment readiness check for Eko SBI platform.
Never prints secret values. Run from backend/ after setting the hosted environment.
"""
from __future__ import annotations
import os, sys, json, urllib.request, urllib.error
from urllib.parse import urlparse

REQUIRED = ("PLATFORM_SESSION_SECRET", "PLATFORM_TOKEN_SECRET", "DATABASE_URL",
            "OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI")

def check_https(name, value, errors, allow_http=False):
    parsed = urlparse(value or "")
    if parsed.scheme not in (("https", "http") if allow_http else ("https",)) or not parsed.netloc:
        errors.append(f"{name} must be an absolute {'HTTP(S)' if allow_http else 'HTTPS'} URL.")

def main():
    errors=[]; warnings=[]
    env=os.getenv("APP_ENV", "").strip().lower()
    if env not in {"production", "hosted"}:
        errors.append("APP_ENV must be production or hosted for this check.")
    missing=[k for k in REQUIRED if not os.getenv(k)]
    if missing: errors.append("Missing required variables: " + ", ".join(missing))
    for key in ("PLATFORM_SESSION_SECRET", "PLATFORM_TOKEN_SECRET"):
        value=os.getenv(key, "")
        if len(value) < 32: errors.append(f"{key} must be at least 32 characters.")
        if value.lower() in {"changeme", "secret", "password", "local-session-secret-change-before-hosting"}:
            errors.append(f"{key} is a known unsafe default.")
    db=os.getenv("DATABASE_URL", "")
    if db and not db.startswith(("postgresql://", "postgresql+psycopg://")):
        errors.append("DATABASE_URL must use PostgreSQL for hosted mode.")
    check_https("OIDC_ISSUER_URL", os.getenv("OIDC_ISSUER_URL", ""), errors)
    check_https("OIDC_REDIRECT_URI", os.getenv("OIDC_REDIRECT_URI", ""), errors)
    frontend=os.getenv("OIDC_FRONTEND_SUCCESS_URL", "")
    if frontend: check_https("OIDC_FRONTEND_SUCCESS_URL", frontend, errors)
    origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
    if not origins: errors.append("CORS_ORIGINS must explicitly list trusted frontend origins.")
    if any("localhost" in x or "127.0.0.1" in x for x in origins):
        errors.append("CORS_ORIGINS contains localhost; use exact hosted origins in production.")
    # Provider discovery reachability check (no client secret is sent).
    issuer=os.getenv("OIDC_ISSUER_URL", "").rstrip("/")
    if issuer:
        try:
            req=urllib.request.Request(issuer + "/.well-known/openid-configuration", headers={"Accept":"application/json"})
            with urllib.request.urlopen(req, timeout=8) as response:
                metadata=json.loads(response.read(1_000_000).decode("utf-8"))
            if metadata.get("issuer", "").rstrip("/") != issuer:
                errors.append("OIDC discovery issuer does not match OIDC_ISSUER_URL.")
            for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not metadata.get(field): errors.append(f"OIDC discovery document is missing {field}.")
        except Exception as exc:
            errors.append(f"OIDC discovery check failed ({type(exc).__name__}); verify issuer URL/network/provider.")
    # PostgreSQL connectivity and schema checks are only attempted when psycopg is installed.
    if db.startswith(("postgresql://", "postgresql+psycopg://")):
        try:
            import psycopg
            conn=psycopg.connect(db.replace("postgresql+psycopg://", "postgresql://", 1), connect_timeout=5)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    if cur.fetchone()[0] != 1: errors.append("PostgreSQL SELECT 1 returned unexpected result.")
                    cur.execute("SELECT to_regclass('public.alembic_version')")
                    row=cur.fetchone()
                    if not row or row[0] is None: errors.append("Alembic migration table is missing; run alembic upgrade head.")
                    cur.execute("SELECT to_regclass('public.organizations'), to_regclass('public.users'), to_regclass('public.background_jobs')")
                    names=cur.fetchone()
                    if any(n is None for n in names): errors.append("Required platform tables are missing; run alembic upgrade head.")
            finally: conn.close()
        except ImportError: errors.append("psycopg is not installed; install backend/requirements.txt.")
        except Exception as exc: errors.append(f"PostgreSQL check failed ({type(exc).__name__}); check credentials, network, and migrations.")
    report={"ready": not errors, "app_env": env, "checks": {"secrets_configured": not any(k in " ".join(errors) for k in ("PLATFORM_SESSION_SECRET", "PLATFORM_TOKEN_SECRET")), "postgresql_url_configured": bool(db), "oidc_discovery_checked": bool(issuer)}, "errors": errors, "warnings": warnings, "totp_2fa": "excluded_by_product_decision", "note": "This check does not perform browser E2E or prove tenant isolation of legacy file-backed routes."}
    print(json.dumps(report, indent=2))
    return 0 if not errors else 2

if __name__ == "__main__": sys.exit(main())
