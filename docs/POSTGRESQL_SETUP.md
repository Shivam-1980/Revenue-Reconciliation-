# PostgreSQL

## Default: built-in PostgreSQL 16 (nothing to install)
`backend/.env` has `EKO_DATABASE=embedded`. `start.bat` / `serve.py` then:
* installs the PostgreSQL programs from the pinned `pgserver` package (included in `backend/requirements.txt`),
* creates the database once in `backend/data/pgdata` (password-protected, `127.0.0.1` only, port `EKO_PG_PORT`, default 54329),
* starts it with the backend and stops it when the backend is closed normally,
* **copies your existing SQLite data** (accounts, uploads, saved months, audit log) into it the first time, checks every table's row count, and leaves the SQLite file untouched (`backend/data/migrated_to_postgresql.txt` records this).

The database password is generated per installation and kept in `backend/data/local_secrets.json` (`EKO_PG_PASSWORD`). Back the database up with `python backup_database.py create` (see `SECURITY_AND_BACKUP.md`).

To look inside: `psql` is in the package, e.g. `%LOCALAPPDATA%\EkoSBI\venv_v62_6_115\Lib\site-packages\pgserver\pginstall\bin\psql.exe -h 127.0.0.1 -p 54329 -U eko_app eko_reconciliation` (password from `local_secrets.json`).

## Alternatives
* `EKO_DATABASE=sqlite`: the local SQLite file `backend/data/platform.sqlite3` (single user, no extra processes).
* An external PostgreSQL server: set `DATABASE_URL=postgresql://user:password@host:5432/eko_reconciliation` (it wins over `EKO_DATABASE`); install PostgreSQL 16 from https://www.postgresql.org/download/windows/ and create a database and user:
  ```sql
  CREATE USER eko_app WITH PASSWORD 'choose-a-strong-password';
  CREATE DATABASE eko_reconciliation OWNER eko_app;
  ```
  Tables are created automatically. To move SQLite data into it once, also set `EKO_MIGRATE_SQLITE=true`.

## What is stored
| Table | Content |
|---|---|
| `src_uploads` | One row per uploaded source file version (kind, file name, period, SHA-256, rows, `is_current`) |
| `src_transaction_rows` / `src_commission_rows` / `src_generic_rows` | Every uploaded row (personal identifiers masked) |
| `recon_runs` / `recon_result_rows` | Every reconciliation run and its CSP x transaction-type results |
| `period_workspaces` | Each reconciled month's uploaded files, **encrypted** (for "Restore month files") |
| `recon_history_snapshots` | Archived monthly snapshots |
| `users`, `auth_*`, `api_keys`, `audit_events` | Sign-in, sessions, API keys, audit trail |

Nothing is overwritten: a new upload of the same kind becomes `is_current = true`; earlier months stay queryable.
