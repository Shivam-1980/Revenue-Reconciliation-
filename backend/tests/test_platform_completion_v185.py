from app import platform_security
from app.platform_models import Base, Organization, PlatformUser, PlatformApiKey, BackgroundJob
from app.services import platform_worker


def test_oidc_status_exposes_no_secret_and_reports_no_second_step():
    data = platform_security.oidc_config_status()
    assert "configured" in data
    assert data["two_factor"] == "none"
    assert "OIDC_CLIENT_SECRET" in data["missing_variables"] or isinstance(data["configured"], bool)
    assert "secret_value" not in str(data).lower()


def test_oidc_status_identifies_google_for_the_sign_in_button_label(monkeypatch):
    assert platform_security.oidc_config_status()["provider"] == "sso"   # no OIDC_ISSUER_URL set: generic label
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://accounts.google.com")
    assert platform_security.oidc_config_status()["provider"] == "google"
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://login.microsoftonline.com/common/v2.0")
    assert platform_security.oidc_config_status()["provider"] == "microsoft"
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://my-org.okta.com")
    assert platform_security.oidc_config_status()["provider"] == "sso"   # not Google/Microsoft: generic label
    assert "secret_value" not in str(platform_security.oidc_config_status()).lower()


def test_postgres_metadata_models_include_tenant_keys():
    assert {"organizations", "platform_users", "platform_api_keys", "platform_background_jobs"}.issubset(Base.metadata.tables)
    assert "organization_id" in PlatformUser.__table__.columns
    assert "organization_id" in PlatformApiKey.__table__.columns
    assert "organization_id" in BackgroundJob.__table__.columns


def test_worker_path_guard_rejects_absolute_paths(tmp_path, monkeypatch):
    from app.services import platform_jobs
    monkeypatch.setattr(platform_jobs, "DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(platform_worker, "WORKSPACE_ROOT", tmp_path / "tenants")
    job = platform_jobs.enqueue("org1", "user1", "file_validation", {"relative_path": str(tmp_path / "outside.xlsx")})
    assert platform_worker.process_one() is True
    status = platform_jobs.get_job(job["id"], "org1")
    assert status["status"] == "failed"
    assert "relative" in (status["error"] or "")


def test_worker_fails_closed_for_unimplemented_financial_job_types(tmp_path, monkeypatch):
    from app.services import platform_jobs
    monkeypatch.setattr(platform_jobs, "DB_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(platform_worker, "WORKSPACE_ROOT", tmp_path / "tenants")
    job = platform_jobs.enqueue("org1", "user1", "reconciliation", {})
    assert platform_worker.process_one() is True
    status = platform_jobs.get_job(job["id"], "org1")
    assert status["status"] == "failed"
    assert "not enabled" in (status["error"] or "")
