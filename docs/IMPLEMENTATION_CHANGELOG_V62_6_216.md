# V62.6.216 - Speed (backend)

Timing only: no rule, amount or output was changed. Measured on this PC (Windows 11, Python 3.10, pandas 2.3.3) with
`tools/benchmark_pipeline.py` on synthetic data (not real SBI/BC files), CSV input, SQLite, the full upload -> run ->
results -> month-save chain, 2 repetitions each, seconds. "Before" is the V62.6.215 code run the same way.

| Rows | Step | Before | After |
|---|---|---|---|
| 50,000 | upload transactions | 2.0 | 1.8 |
| 50,000 | run reconciliation | 6.8 | 6.2 |
| 50,000 | save month (history snapshot) | 3.2 | 2.5 |
| 50,000 | **all steps** | **15.1** | **13.4** |
| 200,000 | upload transactions | 5.9 | 5.2 |
| 200,000 | run reconciliation | 24.1 | 20.0 |
| 200,000 | save month (history snapshot) | 11.0 | 8.7 |
| 200,000 | **all steps** | **51.7** | **43.3** |

The gain is about 11 % (50k rows) to 16 % (200k rows) of the whole chain. The two tasks in the status sheet are only
partly done: the double commission calculation was already removed in V62.6.215 (the second request is answered from
the first), and the remaining time is spread over many pandas steps rather than one slow spot.

## What changed
* **Text handling once per distinct value** (`services/fast_text.py`). `.str` methods on a column run as a Python loop,
  but CSP, transaction type, status, `rate_status` and `mapping_confidence` hold a few hundred distinct values in
  hundreds of thousands of rows. `on_unique` runs the operation on the distinct values and spreads the result back
  (missing values included). Used in upload validation, the processing snapshot, successful-transaction filtering,
  expected-commission preparation, the reconciliation/condition-audit flags and the dashboard source summary.
  Columns that are mostly unique (transaction references) and small columns use the plain code.
* **Validation and snapshot** strip each text column once and reuse it (it was stripped 2-3 times) and parse the date
  column once.
* **Expected commission**: a transaction date that is already a real datetime is no longer printed to text and parsed
  again; `map` calls on the KYC/type columns run once per distinct value.
* **Cached result** (`reconciliation_cache.read_cached`): the cached CSV was re-read about ten times per run; it is now
  parsed once per file version (size + modification time of the data and meta file) and every caller gets its own copy.
  Any rewrite or `clear_cache()` drops the stored copy.
* **Month snapshot** (`reconciliation_history._safe`): finite numbers and containers of plain values skip the slow
  type checks (about 3x faster for the 70 MB snapshot at 200k rows).
* `tools/benchmark_pipeline.py`: `--profile` (also profiles the API's worker threads), `--database embedded` (built-in
  PostgreSQL on its own port inside the throwaway folder), `--save-responses` (keeps each GET response for comparison).

## Output check
* 20 generated files (history snapshot 70 MB, condition-audit CSV, transactions, commission, cache, processing snapshot,
  upload metadata ...) from the 200,000-row run: byte-identical to V62.6.215 after masking only run ids, batch ids and
  timestamps.
* API responses (`/csp`, `/exceptions`, `/dashboard/summary`, `/status`) at 50,000 rows: identical apart from upload
  timestamps and batch ids.
* New tests `tests/test_v626216_speed_equivalence.py` compare every shortcut with the plain pandas code (shortcut switched
  off), the snapshot cleaner with its previous version, and the cache memo for isolation and invalidation.

## Tried and not kept
* A vectorised `aggregate_by_csp` was 2x faster but changed the last digits of `expected_commission` for 2-3 % of CSPs on
  the real August and September results (different summation order), so it was reverted. The per-CSP Python aggregation
  stays; with the real ~500 CSPs it costs well under a second.

## Not done
* Reconciliation is still about 20 s at 200,000 rows (target about 15 s): the rule matching, condition audit, the 70 MB
  snapshot write and result conversion are each a few seconds and need separate, careful changes.
* The numbers above are SQLite. One V62.6.215 run on the built-in PostgreSQL (50,000 rows) gave a similar run time
  (7.3 s); the new code was not timed on PostgreSQL. The database insert of the month is about 1 s at 200,000 rows.

## Authentication
* The e-mailed one-time code (OTP) and the whole SMTP e-mail system were removed at the user's request. `/api/auth/login` now opens the session directly after the password check; `/api/auth/login/verify` and `/api/auth/login/resend` no longer exist. `REQUIRE_EMAIL_OTP`, `SMTP_*`, `EMAIL_DELIVERY` settings, `docs/EMAIL_SMTP_SETUP.md`, `backend/test_email_settings.py`, the dev outbox and the OTP/SMTP lines of the security checklist are gone. `/api/auth/status` reports `two_factor: "none"`.
* Sign-in is now e-mail + password, plus the optional "Continue with Google" button once OIDC is configured. Lockout after 5 wrong passwords, per-IP rate limits, idle timeout, HttpOnly/SameSite=Strict cookie and CSRF are unchanged.
* **Security downgrade:** a password alone now gives access (also in hosted mode, where the code used to be mandatory). Use strong passwords and keep HTTPS on before any network use. The unused `auth_otp_challenges` table stays in the schema/migration.
* Tests: OTP tests replaced by password-only login tests (no `mfa_required`, old verify/resend endpoints unusable, status `two_factor == "none"`, checklist without `two_step`/`smtp`). Full suite 416 passed, 8 skipped.

## September verification (1 Nov 2026)
* The September files (Successful Transactions, BC report and the 8 supporting files) were run through the app and re-calculated separately from the SBI rate workbook.
* Fixed: when one CSP had both Money Transfer and Fund Transfer, the bank's combined commission was counted on both rows. Each is now matched to its own bank line (`BC_OWN_LINE_TYPES` in `reconciliation_engine.py`).
* Fixed: a TOTAL footer line in the Passbook Printing file was counted as a CSP. It is now ignored, like the TOTAL rows in the mATM, TAB and Loan Lead files.
* Test added: `test_v626216_sep_verification_fixes.py`.

## SBI "Updated Commission Structure 01.04.2025" PDF applied (3 Nov 2026)
* The PDF (4 pages, 29 items) was compared with the rules workbook line by line: every rate in the PDF matches the workbook. The workbook also carries lines that are NOT in the PDF (AEPS acquirer Rs 1, YONO Rs 15, Fund Transfer Non-Home flat Rs 10, e-KYC certificate Rs 25, passbook printer Rs 610, inactivity penalty); they come from the company's Excel.
* The PDF has no line for AEPS ONUS / AEPS acquirer / debit-card / mATM / YONO transactions: they are cash withdrawals, deposits or transfers. Bank payments checked on two months follow those schedules.
* `apply_sbi_pdf_schedule_rules` (rate_master.py): the generic schedules CM010/012/013/019/020/051 are now CONFIRMED (AEPS ONUS withdrawal / deposit / fund transfer, mATM-ATM deposit / transfer, Loan Deposit as un-mapped = cash deposit); AEPS ACQUIRER WITHDRAWAL, DEBIT CARD ONUS / OFFUS and YONO CASH use the Cash Withdrawal schedule; the Excel-only Rs 1 and Rs 15 rates are removed.
* Mapping master: Withdrawal, AEPS OFFUS Withdrawal, ATM Onus / Offus Withdrawal, ATM Deposit, ATM Fund Transfer and Deposit are EXACT (were PROBABLE).
* **Money Transfer** now uses the Remittance (Cash) non-home schedule (item 6.a), not home-branch 6.b. Checked on two months: for agents whose counts agree exactly, almost all bank payments equal the 6.a amount. FUND TRANSFER stays on 6.b. To revert, change the Money Transfer row in `transaction_type_mapping_master.csv`.
* Tests: `test_v626216_sbi_pdf_rules.py` added; the two tests that encoded Money Transfer = 6.b were updated.

## Screens: new look for the remaining pages and dark mode finished (3 Nov 2026)
* Transactions (Transaction Traceability), Period Analysis, Source data pages (Successful Transactions, BC Commission Data, SBI Expected Commission Rule), Data Processing and Audit & Reports now use the same layout as the Reconciliation page: title and plain-words description, one-line statistics, filters, a clean table and Previous / Next. Wording is plain ("Should earn", "Actually paid", "Agent"). Calculations and data are untouched.
* New small components in `main.jsx`: `PageToolbar`, `MiniStats`, `SearchField`, `Pager`, `Notice`; styles in `theme.css` (dark versions are generated by `scripts/gen-dark.mjs` plus `scripts/dark-extra.css`).
* Contrast checked on every menu page in both themes with a script: dark mode 0 problems (3 fixed: Data Upload "More details" links, the Daily/Monthly switch, the new notices); light mode pale grey text raised from 2.3-4.4 : 1 to at least 4.5 : 1 and the smallest text sizes made a little larger.
* Checked in a browser on a test copy (empty state; real rows could not be shown there because the app clears the workspace on page load).

## Speed (reconciliation about 18 s -> about 14.5 s on the real September file) and reaching the app from another computer (3 Nov 2026)
* Speed: the same period text was parsed about 6,500 times per run: `_period_month` (reconciliation_engine.py, social_security_rules.py) now parses each distinct text once (`lru_cache`). The m-ATM and PMJJBY/PMSBY comparisons were calculated twice per run (dashboard, then month save): `services/result_memo.py` hands the second call a copy of the first answer while none of the input files has changed (any upload, reset or restore calculates again; `EKO_NO_RESULT_MEMO=1` switches it off). Compared with it switched off, all 26 result files are identical apart from run ids, batch ids and timestamps. Measured back to back: run 14.5 s with the re-use (the PC was slower during the comparison run, so only the ratio run / upload is reliable: 1.04 against 1.31 before).
* Another computer: `EKO_BIND_HOST` (backend/.env, default 127.0.0.1). `0.0.0.0` listens on every network address of the PC and prints the addresses; `serve.py` refuses to start on a network address without `EKO_HTTPS=true` (or `EKO_BEHIND_PROXY=true`); the certificate is remade automatically so that it names this PC's network addresses (`make_local_cert.py`: `lan_addresses`, `_covers`). `allow_network_access.bat` (run once as administrator) opens port 8000 for the private network only. Steps in `docs/AGENT_API.md` section 0.
* Tested on this PC through its own network address (192.168.30.160): health over TLS with the certificate checked = healthy; plain HTTP refused; API without a key 401; with a read key 200; a write with the read key 403; the certificate lists the address. Not yet tried from a second computer, and the Windows firewall step has to be done by the owner.
* Tests: `test_v626216_network_access.py` (5), `test_v626216_speed_memo.py` (11).
* Hand-over for the other computer: `backend\make_agent_kit.py` writes `agent_kit\` (certificate, address, `check_agent_connection.py`); the checker (plain Python, nothing to install) prints PASS / FAIL for: PC answers over a locked connection, no key is refused, the key can read. Tried against a backend in network mode: correct certificate and key = 3 PASS; wrong key = FAIL on step 3; no certificate = refused (self-signed certificate is not trusted by default). Tests: `test_v626216_agent_check.py` (3).
* Google sign-in check: `backend\check_google_login.py` (plain-words PASS / FAIL, no secret printed) and `docs\GOOGLE_SIGN_IN.md`. On the live copy: settings saved, the app reports Google as ready, the sign-in page shows "Continue with Google", Google answers 302 for the new Client ID and the return address (no deleted_client / mismatch error), and name@eko.co.in exists as an active super_admin. The final real sign-in has to be done by that person.
* Owner security steps: the security checklist (Audit & Reports) now reads BitLocker without administrator rights (Windows shell property) and tells a second physical disk from a second drive letter (this PC's C:, D: and E: are partitions of ONE disk, so a backup on E: is not a second copy; a OneDrive or network folder is). `owner_security_steps.bat` walks the owner through the key copy, the backup folder (writes EKO_BACKUP_DIR, makes and checks a backup there) and the BitLocker page; nothing changes until the owner types the folder and confirms. On this PC BitLocker is ON for C:, D: and E:. Still to be decided by the owner: where the key copy and the backups go. Tests: `test_v626216_owner_steps.py`.

## AI harness checked on the real September result and fixed (3 Nov 2026)
* All 6 tools and the triage / investigate endpoints were run on a full month of data and compared with the dashboard and raw data. Unchanged and correct: read-only guardrails (unknown tool refused, `explain_variance` with no filter refused with 400), `validate_upload` for the main files, `resolve_csp_identity`, `calculate_expected_commission` (matches the engine), `explain_variance`.
* Fixed: `reconcile_period` always reported 0 matched groups / 0% because it looked for the label "Matched" while the engine writes "MATCH". It now counts MATCH and returns the dashboard's own count-control rate.
* Fixed: `calculate_kpi` asked for two field names the dashboard does not have (`transaction_only_reconciliation_rate`, `matm_control_groups`) and silently left them out; it now asks for real names (m-ATM, DFS, Women CSP, PMJJBY/PMSBY, TAB, Rural matched / total as well) and lists any field that is not available.
* Fixed: the priority queue took the first N rows of the exception table and ranked only those, so an urgent case further down never appeared (September: 5,907 exceptions; the first 500 held 0 urgent cases, the whole table holds 2 urgent and 378 high). Every exception is now ranked and the top N returned, with the counts for all exceptions.
* Fixed: `EVIDENCE_REQUIRED` (493 exceptions) had no explanation and the lowest priority; it now explains the missing proof and ranks at 36.
* Fixed: `validate_upload` said "not uploaded" for DFS, Women CSP, TAB, m-ATM and Loan Lead although the files were there; it now reads their own metadata files.
* Still true: no LLM is connected; ranking is a fixed rule-based score and says so. Tests: `test_v626216_ai_harness_fixes.py` (5).

## Easy filters for auditors (Nov 2026)
- One shared filter bar (frontend only, no calculation touched): chips with a count on every option, drop-down for long lists (product, reason), chips showing what is applied (click to remove), "Showing X of Y" line, "Clear all filters". Counts follow the other filters that are already on.
- Added to Exception Center (reason, status, severity, product), CSP Analysis (result, amount difference, count difference), Transaction Analysis (calculation, count difference).
- New page "CSP Transaction Counts": every agent x transaction type with file count, bank count, difference, biggest differences first; filters for product, count (file has more / bank has more / same / not in bank report) and result; downloads exactly the filtered list.
- CSP Analysis, CSP Transaction Counts and Exception Center are now in the left menu and the Ctrl+K search.
- Month filter is not added: the dashboard shows one uploaded month at a time (use Period Analysis for date ranges).
- Filters work for any month: options come from the rows of the month being shown. When a saved earlier month is opened from 'Reconciled month', CSP Transaction Counts shows that month (its title names the month), not the current workspace. Options with no rows stay visible but dimmed, so the bar does not jump.
- CSP Transaction Counts now opens with a 'By CSP' view: for every CSP the transactions in the successful sheet, in the bank (actual) report and the difference (largest first), how many types differ, and sheet transactions of types the bank report does not list (shown separately, not counted as a difference). 'See types' drills into that CSP; 'By CSP and type' is the detailed view. Works for the current and any saved month; download follows the view.
