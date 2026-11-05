# PostgreSQL metadata cutover checklist (V62.6.186)

1. Back up `backend/data/platform.sqlite3` and all financial source/result files.
2. Set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` and install `backend/requirements.txt`.
3. From `backend/`, run `alembic upgrade head`.
4. Preview existing metadata: `python scripts/migrate_platform_sqlite_to_postgres.py --dry-run`.
5. After reviewing counts, run `python scripts/migrate_platform_sqlite_to_postgres.py` once. It uses a transaction and aborts on conflicting rows; do not repeatedly run it against already copied data without a deliberate merge plan.
6. Restart the API and smoke-test `/health`, `/api/auth/status`, login, workspace listing, user/admin APIs, API-key create/revoke, job submit/list/status and worker `--once`.
7. Do not set `APP_ENV=hosted` for real business use until tenant-aware source/reconciliation storage and route-level authorization have been migrated. The current hosted guard intentionally blocks those routes.

This migration covers platform metadata/job records only. It does not copy or re-key the financial transaction workbooks, reconciliation outputs, or uploaded files.
