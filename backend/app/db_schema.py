"""Unified database schema (V62.6.207): platform, security and business data.

One schema for both engines: PostgreSQL in production (DATABASE_URL) and SQLite for a
local install without PostgreSQL. Platform/security table names and column types match
the raw SQL used by platform_security/security_core (integer epoch timestamps, 0/1 flags).

Business tables keep every upload and every reconciliation run as its own record. A newer
upload of the same kind only flips ``is_current``; nothing is overwritten, so earlier
months stay queryable and are never mixed into the current workspace.
"""
from sqlalchemy import (JSON, BigInteger, Boolean, Column, ForeignKey, Index, Integer, LargeBinary, MetaData, Numeric, String, Table, Text,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
Json = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(18, 4)

# --- Platform identity (names/types identical to migration 20261027_0001) -------------
organizations = Table("organizations", metadata,
    Column("id", String(64), primary_key=True), Column("name", String(160), nullable=False),
    Column("created_at", BigInteger, nullable=False), Column("active", Integer, nullable=False, server_default="1"))
users = Table("users", metadata,
    Column("id", String(64), primary_key=True), Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", String(512), nullable=False), Column("role", String(24), nullable=False),
    Column("organization_id", String(64), ForeignKey("organizations.id")),
    Column("active", Integer, nullable=False, server_default="1"), Column("created_at", BigInteger, nullable=False))
audit_events = Table("audit_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True), Column("actor_user_id", String(64)),
    Column("organization_id", String(64)), Column("event_type", String(100), nullable=False),
    Column("detail_json", Text, nullable=False), Column("created_at", BigInteger, nullable=False, index=True))
api_keys = Table("api_keys", metadata,
    Column("id", String(64), primary_key=True), Column("name", String(100), nullable=False),
    Column("key_hash", String(64), nullable=False, unique=True),
    Column("organization_id", String(64), ForeignKey("organizations.id"), nullable=False),
    Column("scopes_json", Text, nullable=False), Column("expires_at", BigInteger, nullable=False),
    Column("revoked", Integer, nullable=False, server_default="0"), Column("created_at", BigInteger, nullable=False))
oidc_login_codes = Table("oidc_login_codes", metadata,
    Column("code_hash", String(64), primary_key=True), Column("access_token", Text, nullable=False),
    Column("expires_at", BigInteger, nullable=False))

# --- Security core (V62.6.206) ------------------------------------------------------
auth_sessions = Table("auth_sessions", metadata,
    Column("id_hash", String(64), primary_key=True), Column("user_id", String(64), nullable=False, index=True),
    Column("csrf_token", String(100), nullable=False), Column("created_at", BigInteger, nullable=False),
    Column("last_seen", BigInteger, nullable=False), Column("expires_at", BigInteger, nullable=False),
    Column("revoked", Integer, nullable=False, server_default="0"), Column("ip", String(64)), Column("user_agent", Text))
auth_otp_challenges = Table("auth_otp_challenges", metadata,
    Column("id", String(100), primary_key=True), Column("user_id", String(64), nullable=False, index=True),
    Column("code_hash", String(64), nullable=False), Column("expires_at", BigInteger, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"), Column("consumed", Integer, nullable=False, server_default="0"),
    Column("created_at", BigInteger, nullable=False), Column("ip", String(64)))
auth_login_throttle = Table("auth_login_throttle", metadata,
    Column("email", String(254), primary_key=True), Column("failed_count", Integer, nullable=False, server_default="0"),
    Column("locked_until", BigInteger, nullable=False, server_default="0"), Column("updated_at", BigInteger, nullable=False))

# --- Business data ------------------------------------------------------------------
src_uploads = Table("src_uploads", metadata,
    Column("id", String(36), primary_key=True),
    Column("kind", String(60), nullable=False), Column("filename", Text), Column("sheet_name", Text),
    Column("sha256", String(64), nullable=False), Column("row_count", Integer, nullable=False),
    Column("period_start", String(10)), Column("period_end", String(10)), Column("batch_id", String(64)),
    Column("uploaded_at", String(40)), Column("source_file", Text, nullable=False),
    Column("synced_at", BigInteger, nullable=False), Column("synced_by", String(100)),
    Column("is_current", Boolean, nullable=False), Column("meta", Json),
    UniqueConstraint("kind", "sha256", "source_file", name="uq_src_upload_content"))
Index("ix_src_uploads_kind_current", src_uploads.c.kind, src_uploads.c.is_current)
Index("ix_src_uploads_period", src_uploads.c.period_start, src_uploads.c.period_end)

src_transaction_rows = Table("src_transaction_rows", metadata,
    Column("upload_id", String(36), ForeignKey("src_uploads.id", ondelete="CASCADE"), primary_key=True),
    Column("row_no", Integer, primary_key=True),
    Column("transaction_id", Text), Column("csp_id", String(64)), Column("transaction_type", Text),
    Column("amount", Money), Column("transaction_date", String(32)), Column("status", String(40)), Column("extra", Json))
Index("ix_src_tx_csp", src_transaction_rows.c.csp_id)
Index("ix_src_tx_type", src_transaction_rows.c.transaction_type)

src_commission_rows = Table("src_commission_rows", metadata,
    Column("upload_id", String(36), ForeignKey("src_uploads.id", ondelete="CASCADE"), primary_key=True),
    Column("row_no", Integer, primary_key=True),
    Column("csp_id", String(64)), Column("transaction_type", Text),
    Column("actual_commission", Money), Column("report_base", Money), Column("extra", Json))
Index("ix_src_cm_csp", src_commission_rows.c.csp_id)

src_generic_rows = Table("src_generic_rows", metadata,
    Column("upload_id", String(36), ForeignKey("src_uploads.id", ondelete="CASCADE"), primary_key=True),
    Column("row_no", Integer, primary_key=True), Column("csp_id", String(64)), Column("data", Json, nullable=False))
Index("ix_src_generic_csp", src_generic_rows.c.csp_id)

recon_runs = Table("recon_runs", metadata,
    Column("run_id", String(64), primary_key=True),
    Column("run_at_utc", String(40)), Column("period_start", String(10)), Column("period_end", String(10)),
    Column("engine_version", String(80)), Column("triggered_by", String(100)), Column("synced_at", BigInteger, nullable=False),
    Column("transaction_sha256", String(64)), Column("commission_sha256", String(64)), Column("rate_master_sha256", String(64)),
    Column("successful_transactions", Integer), Column("exception_groups", Integer), Column("result_rows", Integer),
    Column("expected_commission", Money), Column("actual_commission", Money), Column("variance", Money),
    Column("settlement_ready", Boolean), Column("is_current", Boolean, nullable=False), Column("summary", Json))
Index("ix_recon_runs_period", recon_runs.c.period_start, recon_runs.c.period_end)

recon_result_rows = Table("recon_result_rows", metadata,
    Column("run_id", String(64), ForeignKey("recon_runs.run_id", ondelete="CASCADE"), primary_key=True),
    Column("row_no", Integer, primary_key=True),
    Column("csp_id", String(64)), Column("transaction_type", Text), Column("join_type", Text),
    Column("successful_transactions", Integer), Column("transaction_amount", Money),
    Column("expected_commission", Money), Column("actual_commission", Money), Column("financial_gap", Money),
    Column("reconciliation_status", String(60)), Column("exception_flag", Boolean), Column("mismatch_reason", Text),
    Column("data", Json))
Index("ix_recon_rows_csp", recon_result_rows.c.csp_id)
Index("ix_recon_rows_status", recon_result_rows.c.reconciliation_status)

recon_history_snapshots = Table("recon_history_snapshots", metadata,
    Column("period_key", String(7), primary_key=True), Column("saved_at", String(40)), Column("sha256", String(64), nullable=False),
    Column("synced_at", BigInteger, nullable=False), Column("synced_by", String(100)), Column("snapshot", Json, nullable=False))

# Every uploaded source file of a reconciled month, stored byte-for-byte (zip) so the month can be
# restored into the workspace without re-uploading (V62.6.211). The permanent SBI rule master is not
# included: a restored month is always recalculated with the current approved rules.
period_workspaces = Table("period_workspaces", metadata,
    Column("period_key", String(32), primary_key=True), Column("period_label", String(64)),
    Column("saved_at", BigInteger, nullable=False), Column("saved_by", String(120)),
    Column("archive", LargeBinary, nullable=False), Column("archive_sha256", String(64), nullable=False),
    Column("size_bytes", BigInteger, nullable=False), Column("manifest", Json, nullable=False))

db_sync_log = Table("db_sync_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True), Column("started_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger), Column("actor", String(100)), Column("trigger", String(120)),
    Column("status", String(20), nullable=False), Column("detail", Json))

BUSINESS_TABLES = ("src_uploads", "src_transaction_rows", "src_commission_rows", "src_generic_rows",
                   "recon_runs", "recon_result_rows", "recon_history_snapshots", "period_workspaces", "db_sync_log")
