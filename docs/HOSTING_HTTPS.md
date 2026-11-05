# HTTPS

## On this PC (local certificate)
1. In `backend\.env` set `EKO_HTTPS=true`.
2. Run `start.bat`. It creates a certificate for `localhost`, `127.0.0.1` and `::1` (`backend\data\certs`), starts the backend and the dashboard on **https://127.0.0.1:8000 / :5173** and opens the dashboard.
3. The browser warns because the certificate is self-signed. Run **`trust_local_cert.bat`** once: it adds the certificate to *your* Windows user's trusted certificates (Windows asks you to confirm). Restart the browser; no more warning.

TLS 1.2+ only; plain HTTP on those ports is refused. Set `EKO_HTTPS=false` to go back to HTTP.

## On a server (other people reach it over a network)
Put the app behind a TLS proxy; do not expose uvicorn directly.

1. Server `backend\.env`: `APP_ENV=hosted`, `EKO_BEHIND_PROXY=true`, `DATABASE_URL=...` (external PostgreSQL) or `EKO_DATABASE=embedded`, `CORS_ORIGINS=https://eko.example.com`, and the secrets (`PLATFORM_TOKEN_SECRET`, `PLATFORM_SESSION_SECRET`, `EKO_ENCRYPTION_KEY`, `EKO_PG_PASSWORD` for embedded PostgreSQL). SMTP must be configured (the e-mail code cannot be switched off in hosted mode).
2. Build the dashboard once: `cd frontend && npm ci && npm run build` (output `frontend/dist`).
3. Use `deploy/Caddyfile` (automatic Let's Encrypt certificates) or `deploy/nginx.conf.example`. Both add HSTS, a Content-Security-Policy, redirect HTTP to HTTPS and cap uploads at 60 MB.
4. In hosted mode the app itself also refuses plain HTTP (`400` for the API, `308` redirect for pages; `/health` stays open for load-balancer probes) and trusts `X-Forwarded-Proto` only when `EKO_BEHIND_PROXY=true`.

For a LAN server with an internal name, create its certificate with `EKO_CERT_HOSTS=eko-server,192.168.1.20 python backend\make_local_cert.py --force` and trust it on each user's PC with `trust_local_cert.bat`, or use your organisation's certificate authority.
