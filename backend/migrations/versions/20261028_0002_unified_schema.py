"""Unified schema: security (sessions, e-mail OTP, lockout) and business data tables.

Revision ID: 20261028_0002
The application also creates missing tables at startup (app.database.init_schema), so
running this migration is optional for a desktop install and recommended for managed PostgreSQL.
"""
from alembic import op

from app.db_schema import metadata

revision = "20261028_0002"
down_revision = "20261027_0001"
branch_labels = None
depends_on = None

NEW_TABLES = ("auth_sessions", "auth_otp_challenges", "auth_login_throttle", "src_uploads", "src_transaction_rows",
              "src_commission_rows", "src_generic_rows", "recon_runs", "recon_result_rows", "recon_history_snapshots", "db_sync_log")


def upgrade():
    metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    for name in reversed(NEW_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
