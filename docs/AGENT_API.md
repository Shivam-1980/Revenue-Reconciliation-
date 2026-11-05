# Agent API (v1) — for the super agent

Base URL (local): `http://127.0.0.1:8000`. Every call sends the header `X-API-Key: <key>`. Machine clients need no cookies and no CSRF token.
The full machine-readable schema is at `GET /openapi.json`.

## 0. Reach it from another computer (V62.6.216)
By default the app listens on this PC only. To let the other agent (or a colleague) connect over the network:
1. In `backend\.env` set `EKO_HTTPS=true` and `EKO_BIND_HOST=0.0.0.0`, then run `start.bat`. The window prints the addresses, for example `https://192.168.1.20:8000`. The app **refuses to start** on a network address without HTTPS.
2. Run `allow_network_access.bat` once **as administrator**. It opens port 8000 in the Windows firewall for your private network only.
3. On the other computer, call `https://<address printed in step 1>:8000` with the header `X-API-Key: <key>` (see section 1). The certificate is self-signed: give the other computer `backend\data\certs\eko-local.crt` to trust (`curl --cacert eko-local.crt ...`, or `verify="eko-local.crt"` in Python), or use your own certificate / HTTPS proxy as in `docs/HOSTING_HTTPS.md`.
4. Make the hand-over folder on this PC with `python make_agent_kit.py` (in `backend`): it writes `agent_kit\` with the certificate, `check_agent_connection.py` and the address. Copy that folder to the other computer (the key goes separately). There run:
   `python check_agent_connection.py --url https://<address>:8000 --key <key> --cacert eko-local.crt`
   It says PASS / FAIL for: the PC answers over a locked connection, no key is refused, the key can read.
5. Or check by hand from the other computer: `curl --cacert eko-local.crt https://<address>:8000/health` should answer `{"status":"healthy"}`; any `/api/...` call without a key answers 401.
Keep this PC switched on and awake while the agent needs the data. Without a key nothing can be read.


## 1. Get a key
On the server, from the `backend` folder (with the app's Python):

```
python create_agent_api_key.py --name super-agent                 # full access (*), valid 90 days
python create_agent_api_key.py --name reporting --scopes read --days 30
python create_agent_api_key.py --list
python create_agent_api_key.py --revoke <key_id>
```

The key is printed **once**; only its SHA-256 hash is stored. Keep it in the agent's secret store, never in code or chat.
Signed-in administrators can also manage keys through `GET/POST /api/auth/api-keys` and `POST /api/auth/api-keys/{id}/revoke`.

| Scope | Allows |
|---|---|
| `read` | Every GET: all data, results, history, dashboard endpoints |
| `write` | Uploads, run reconciliation, archive month, clear workspace, sync (also implies read) |
| `admin` | Users, organisations, API keys, audit log (also implies read) |
| `*` | Everything (acts as super_admin) |

Every state-changing call is written to the audit log with the key id. The rate limit is 1,200 requests per minute per key. **SBI commission rules can't be changed through any API**: the approved rule workbook is permanent and human-controlled.

## 2. Conventions
- **Money** is an exact decimal string (`"1000.5"`). `null` means *not available*, never zero.
- **Pagination:** `limit` (max 5000) plus `after_row` (or `after_id`). Keep requesting with `after_row = next_cursor` until `next_cursor` is `null`.
- **Months:** each upload is a separate record. Endpoints default to the **current** upload or run; pass `upload_id` or `run_id` to read an older month.
- **Freshness:** the database is synced automatically after every upload, run and archive (in the background, usually within seconds). Call `POST /api/agent/v1/sync` to make it current immediately before reading.

## 3. Read endpoints (`/api/agent/v1`)
| Endpoint | Returns |
|---|---|
| `GET /capabilities` | Your identity and scopes, and every callable endpoint |
| `GET /summary` | Current uploads, current run totals, archived months, last sync |
| `GET /uploads?kind=&current_only=&period=YYYY-MM` | Upload records (file, period, rows, SHA-256, is_current) |
| `GET /uploads/{upload_id}` | One upload |
| `GET /transactions?upload_id=&csp_id=&transaction_type=&after_row=&limit=` | Successful-transaction rows (other source columns in `extra`) |
| `GET /commissions?upload_id=&csp_id=&after_row=&limit=` | BC commission rows |
| `GET /source-rows/{upload_id}?csp_id=` | Rows of any other upload (Women CSP, m-ATM, TAB, DFS, Passbook, PMJJBY/PMSBY, rate master, …) |
| `GET /runs?period=YYYY-MM` | Reconciliation runs with totals |
| `GET /runs/current` or `/runs/{run_id}` | One run with its full summary |
| `GET /runs/{run_id}/results?csp_id=&status=&exceptions_only=true` | CSP × transaction-type results (`run_id` may be `current`) |
| `GET /history`, `GET /history/{YYYY-MM}` | Archived monthly snapshots |
| `GET /csps/{csp_id}` | 360° view of one CSP: transactions by type, BC commission rows, supplementals, results |
| `GET /audit-events?after_id=&event_type=` | Audit trail (admin scope) |

All existing web-app GET routes also work with a key, for example `/api/dashboard/summary`, `/api/reconciliation/exceptions`, `/api/database/status`.

## 4. Actions
| Call | Effect |
|---|---|
| `POST /api/workspace/clear-current-data` | Start a clean current period (history is kept) |
| `POST /api/upload/transactions` (multipart `file`) | Successful-transaction file (CSV/XLSX) |
| `POST /api/upload/commission` (multipart `file`) | BC commission report |
| `POST /api/upload/...` | Supplemental uploads (see `/openapi.json`) |
| `POST /api/reconciliation/run` | Run reconciliation on the current uploads |
| `POST /api/reconciliation/history/archive-current` | Archive the current month |
| `POST /api/agent/v1/sync` | Sync the database now |

## 5. Example (Python)
```python
import os, httpx
api = httpx.Client(base_url="http://127.0.0.1:8000", headers={"X-API-Key": os.environ["EKO_API_KEY"]}, timeout=120)

with open("Success_Sep.xlsx", "rb") as f:
    api.post("/api/upload/transactions", files={"file": f}).raise_for_status()
with open("BC_Report_Sep.xlsx", "rb") as f:
    api.post("/api/upload/commission", files={"file": f}).raise_for_status()
api.post("/api/reconciliation/run").raise_for_status()
api.post("/api/agent/v1/sync").raise_for_status()

cursor, exceptions = 0, []
while True:
    page = api.get("/api/agent/v1/runs/current/results",
                   params={"exceptions_only": True, "after_row": cursor, "limit": 1000}).json()
    exceptions += page["items"]
    if page["next_cursor"] is None:
        break
    cursor = page["next_cursor"]
```

## 6. Errors
`401` missing/invalid/expired/revoked key · `403` scope too small · `404` not found or no current data · `422` bad parameters · `429` rate limit · `500` with a reason (for example sync failure). The body is always `{"detail": "..."}`.
