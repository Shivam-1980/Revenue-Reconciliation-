# V62.6.214 - built-in PostgreSQL, encryption, backups, HTTPS, faster XLSX

## Database
* Built-in PostgreSQL 16 (`pgserver`, no installer): scram-sha-256 password, 127.0.0.1:54329, supervised by `serve.py` (`app/embedded_pg.py`). `EKO_DATABASE=embedded|sqlite`; `DATABASE_URL` still overrides.
* One-time, verified SQLite -> PostgreSQL migration (`services/sqlite_migration.py`); the SQLite file is left untouched.
* Row writes are chunked (20 000 rows per transaction) so the database is never locked for a whole upload.

## Security
* AES-256-GCM chunked encryption for saved months (`crypto_store.py`, `period_store.py`); tamper/wrong-key detection; legacy plain archives are encrypted once.
* PII masked in stored rows (`services/privacy.py`, `db_sync.py`).
* Secrets generated per install (`secret_store.py`); `backend/data` limited to the current Windows user.
* Encrypted logical backups (`services/backup.py`, `backup_database.py`, `/api/database/backup(s)`): create, list, verify, restore, daily + after each saved month, retention.
* HTTPS: local certificate (`make_local_cert.py`, `trust_local_cert.bat`), `EKO_HTTPS`, hosted-mode enforcement, proxy header trust only with `EKO_BEHIND_PROXY`, Caddy/nginx samples.
* `tools/security_scan.py`; `tools/package_release.py` never ships keys, certificates, databases or backups.

## Speed
* `xlsx_scan.py`: single-pass scanner; big sheets are split at row boundaries and scanned on several cores (output identical to the previous parser, proven by tests). Real 2-lakh-row workbook upload 16.2 s -> 12.1 s; remaining time is mostly pandas validation (about 3 s), snapshot (2 s) and CSV writing (1.7 s), which were left unchanged to keep every calculation identical.

## Docs
`SECURITY_AND_BACKUP.md`, `HOSTING_HTTPS.md`, `POSTGRESQL_SETUP.md`.

## Known limits
* HTTPS is off by default locally (`EKO_HTTPS=true` to enable).
* Current-month working CSV files stay plain on disk; use BitLocker.
* SaaS UI redesign (milestone 5) is not part of this release.

## Addendum (V62.6.215 work, same release line)
* UI: text-size control, Ctrl+K search, mobile menu drawer, guided Upload page, security checklist.
* Speed: identical big columns are parsed once (dates, amounts); distinct-value mapping for transaction-type/CSP normalisation; faster month archive (no re-compression of .xlsx). Measured on the real 28 MB September file: outputs byte-identical to before; reconciliation 33.1 s -> 31.8 s. The remaining time is the expected-commission calculation (run twice, about 7.4 s each) and the month archive (about 11 s); removing the duplicate calculation needs a separate, carefully verified change.
* Released as **62.6.215-ui-security-speed** (ZIP in D:\31a\release). Adds the one-time reuse of the duplicate expected-commission calculation (output verified byte-identical) and the background auto-run of the reconciliation after the required files are validated (banner with Run now / Cancel).
