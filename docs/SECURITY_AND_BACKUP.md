# Security, encryption and backups (V62.6.214)

## What is protected, and how
| Area | Protection |
|---|---|
| Sign-in | Password (no e-mailed code), lockout after 5 wrong passwords, rate limits, 30-minute idle timeout, HttpOnly + SameSite=Strict + Secure (over HTTPS) cookie, CSRF token on every change |
| Roles / API | viewer (read-only), operator, org_admin, super_admin; API keys with scopes `read` / `write` / `admin` / `*`; every change is written to the audit log |
| Database | Built-in **PostgreSQL 16**: password-only login (scram-sha-256), listens on `127.0.0.1` only. Data folder `backend/data/pgdata` |
| Saved months | The uploaded source files of every reconciled month are stored **encrypted** (AES-256-GCM); tampering or a wrong key makes them fail to open |
| Personal identifiers | Account numbers, mobile numbers and e-mail addresses are stored **masked** (last 4 characters only) in the database copy that other systems and the agent API read. Older rows are masked automatically once |
| Backups | Encrypted `.ekobak` files, automatic daily and after every saved month (see below) |
| Files on disk | `backend/data` (secrets, database, backups, certificates) is limited to your Windows user, SYSTEM and Administrators |
| Network | Optional HTTPS (`EKO_HTTPS=true`), TLS 1.2+ only, HSTS; hosted mode refuses plain HTTP |
| Dependencies | `python tools/security_scan.py` checks Python and JavaScript packages for known vulnerabilities (last run: none found) |

**Not covered by the app:** the working files of the **current** month (`backend/app/data/transactions`, `commissions`, `supplemental`) are plain CSV because the calculation needs them; they are cleared on every start. Use **BitLocker** (Windows Settings > Privacy & security > Device encryption) so a lost laptop or disk exposes nothing.

## The encryption key: keep a copy
Everything encrypted (saved months, backups) needs the key in `backend/data/local_secrets.json` (`EKO_ENCRYPTION_KEY`). **If that file is lost, encrypted data cannot be recovered.** Save a copy somewhere other than the backups:

```
python backup_database.py export-key --out D:\private\eko_keys.txt
```

Hosted/production: set `EKO_ENCRYPTION_KEY`, `PLATFORM_TOKEN_SECRET`, `PLATFORM_SESSION_SECRET` in the environment (they are required there).

## Backups
Run these from the `backend` folder with the backend's Python (`%LOCALAPPDATA%\EkoSBI\venv_v62_6_115\Scripts\python.exe`):

| Command | What it does |
|---|---|
| `python backup_database.py create` | Backup now (all tables: users, uploads, results, saved months, history, audit log) |
| `python backup_database.py list` | Show backups |
| `python backup_database.py verify <file>` | Decrypt and check every table's row count (changes nothing) |
| `python backup_database.py restore <file>` | Load into an **empty** database |
| `python backup_database.py restore <file> --force` | Replace everything in the current database |

Also available to administrators: `POST /api/database/backup` and `GET /api/database/backups`.

* **Automatic:** one backup per day when the app starts, and one (at most every 30 minutes) after each month is saved. The newest `EKO_BACKUP_KEEP` (default 14) are kept.
* **Where:** `backend/data/backups`. **Set `EKO_BACKUP_DIR` to another drive or a OneDrive folder** (in `backend/.env`): a backup on the same disk does not survive a disk failure. Backups are encrypted, so a cloud folder is safe.
* **Restore after a disaster:** install the app, copy back `local_secrets.json` (or set `EKO_ENCRYPTION_KEY`), start the app once so it creates the empty database, stop it, then `python backup_database.py restore <file>`.

## Passwords and people
Users are created with `python create_platform_admin.py --email ... --role ...`. Use 14+ character passwords. Remove access by deactivating the user in the database (`active = 0`) or revoking API keys with `python create_agent_api_key.py --revoke <id>`.

## Security checklist (V62.6.215)
Audit & Reports (administrators) now opens with a **Security checklist**: database, HTTPS, encryption-key copy, off-disk backups, backup freshness, data-folder access and BitLocker. Each item says what is active or the one step still left for you (the same data: `GET /api/database/security-posture`). `export-key` marks the key as copied. Automated attack-style tests (`tests/test_v626215_security_selftest.py`) check every API route: anonymous callers get 401, a viewer cannot reach any write route, injection / path-traversal probes leak nothing.
