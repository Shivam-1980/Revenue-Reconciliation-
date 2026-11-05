"""Checks the Google sign-in set-up in plain words, without signing anyone in (V62.6.216).

    python check_google_login.py --email name@eko.co.in

Run it from the backend folder with the app's Python while the app is running. It never prints the secret.
The very last step (signing in with the real Google account) can only be done by that person, in the browser.
"""
import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ap = argparse.ArgumentParser()
ap.add_argument("--email", help="the work e-mail that will sign in with Google")
ap.add_argument("--api", default=os.getenv("EKO_API", "http://127.0.0.1:8000"))
a = ap.parse_args()

from dotenv import dotenv_values
env = dotenv_values(HERE / ".env")
results = []


def step(name, ok, detail=""):
    results.append(ok); print(("PASS  " if ok else "FAIL  ") + name + (f"  - {detail}" if detail else ""))


issuer, cid, secret, redirect = (env.get(k, "").strip() for k in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"))
step("1. The four Google settings are in backend\.env", all([issuer, cid, secret, redirect]),
     "" if all([issuer, cid, secret, redirect]) else "missing: " + ", ".join(k for k, v in (("OIDC_ISSUER_URL", issuer), ("OIDC_CLIENT_ID", cid), ("OIDC_CLIENT_SECRET", secret), ("OIDC_REDIRECT_URI", redirect)) if not v))
step("2. The Client ID looks like a Google one and the secret is filled", cid.endswith(".apps.googleusercontent.com") and len(secret) >= 10)
step("3. The return address is this app's callback", redirect.endswith("/api/auth/oidc/callback"), redirect)

try:
    with urllib.request.urlopen(a.api + "/api/auth/oidc/config-status", timeout=10) as r:
        import json; cfg = json.loads(r.read().decode())
    step("4. The running app reports Google sign-in as ready", bool(cfg.get("configured")) and cfg.get("provider") == "google", f"provider {cfg.get('provider')}")
except Exception as e:
    step("4. The running app reports Google sign-in as ready", False, f"{type(e).__name__}: app not reachable at {a.api}")


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


try:
    opener = urllib.request.build_opener(_NoFollow)
    try:
        opener.open(a.api + "/api/auth/oidc/login", timeout=10)
        google_url = None
    except urllib.error.HTTPError as e:
        google_url = e.headers.get("Location")
    ok = bool(google_url) and urllib.parse.urlparse(google_url).netloc == "accounts.google.com" and cid in google_url
    step("5. The app sends people to Google with this Client ID", ok)
    if ok:
        try:
            req = urllib.request.Request(google_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.build_opener(_NoFollow).open(req, timeout=15) as r:
                code, body = r.status, r.read(4000).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read(4000).decode("utf-8", "replace")
        bad = any(w in body.lower() for w in ("deleted_client", "invalid_client", "redirect_uri_mismatch", "error 400", "error 401"))
        step("6. Google accepts the Client ID and the return address", code in (200, 302, 303) and not bad, f"Google answered {code}")
except Exception as e:
    step("5. The app sends people to Google with this Client ID", False, f"{type(e).__name__}: {e}")

if a.email:
    try:
        from app import database
        from sqlalchemy import text
        with database.get_engine().connect() as c:
            row = c.execute(text("SELECT role, active FROM users WHERE lower(email)=:e"), {"e": a.email.strip().lower()}).first()
        step(f"7. {a.email} exists in the app and is active", bool(row and row[1]), "no such user: add it with create_platform_admin.py" if not row else f"role {row[0]}")
    except Exception as e:
        step(f"7. {a.email} exists in the app and is active", False, f"{type(e).__name__}: {e}")

print("\nSet-up is ready." if all(results) else "\nSomething is not ready: see the FAIL lines above.")
print("Last step (only that person can do it): open the app, press 'Continue with Google' and sign in with the work account.")
sys.exit(0 if all(results) else 1)
