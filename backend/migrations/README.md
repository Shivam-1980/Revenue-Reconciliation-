# Platform metadata PostgreSQL cutover

1. Configure `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` and install `backend/requirements.txt`.
2. Apply schema: from `backend`, run `alembic upgrade head`.
3. Optional local metadata copy: `python scripts/migrate_platform_sqlite_to_postgres.py --dry-run`, review counts, then rerun without `--dry-run`. The copy is transactional and aborts on conflicts; take a backup first.
4. Restart the API and verify `/api/auth/status`, login, organisation/user management, API-key lifecycle and background jobs.

When `DATABASE_URL` is PostgreSQL, platform auth/admin and platform job APIs use PostgreSQL. Without it, they continue using local SQLite. Financial source workbooks and legacy reconciliation result files are NOT migrated by this script. Hosted business routes intentionally remain fail-closed until the tenant-aware source/reconciliation repositories and authorization checks have been migrated and verified. Do not open hosted business routes just because the metadata migration succeeds.
