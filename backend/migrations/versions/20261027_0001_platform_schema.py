"""Create hosted platform metadata schema.

Revision ID: 20261027_0001
"""
from alembic import op
from app.platform_models import Base
revision = "20261027_0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    # Compatibility tables used by the existing platform auth/admin APIs. Their
    # names and integer epoch timestamps deliberately match the SQLite local store.
    op.execute("CREATE TABLE IF NOT EXISTS users (id VARCHAR(64) PRIMARY KEY, email VARCHAR(254) NOT NULL UNIQUE, password_hash VARCHAR(512) NOT NULL, role VARCHAR(24) NOT NULL CHECK (role IN ('super_admin','org_admin','operator','viewer')), organization_id VARCHAR(64) REFERENCES organizations(id), active INTEGER NOT NULL DEFAULT 1, created_at BIGINT NOT NULL)")
    op.execute("CREATE TABLE IF NOT EXISTS audit_events (id BIGSERIAL PRIMARY KEY, actor_user_id VARCHAR(64), organization_id VARCHAR(64) REFERENCES organizations(id), event_type VARCHAR(100) NOT NULL, detail_json TEXT NOT NULL, created_at BIGINT NOT NULL)")
    op.execute("CREATE TABLE IF NOT EXISTS api_keys (id VARCHAR(64) PRIMARY KEY, name VARCHAR(100) NOT NULL, key_hash VARCHAR(64) NOT NULL UNIQUE, organization_id VARCHAR(64) NOT NULL REFERENCES organizations(id), scopes_json TEXT NOT NULL, expires_at BIGINT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created_at BIGINT NOT NULL)")
    op.execute("CREATE TABLE IF NOT EXISTS oidc_login_codes (code_hash VARCHAR(64) PRIMARY KEY, access_token TEXT NOT NULL, expires_at BIGINT NOT NULL)")
    op.execute("CREATE TABLE IF NOT EXISTS background_jobs (id VARCHAR(64) PRIMARY KEY, organization_id VARCHAR(64) NOT NULL REFERENCES organizations(id), created_by VARCHAR(64) NOT NULL, job_type VARCHAR(40) NOT NULL, payload_json TEXT NOT NULL, status VARCHAR(20) NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, result_json TEXT, error TEXT)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_org_status ON background_jobs(organization_id,status,created_at)")

def downgrade():
    for table in ("background_jobs", "oidc_login_codes", "api_keys", "audit_events", "users"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
