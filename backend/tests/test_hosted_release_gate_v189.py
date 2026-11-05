from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_hosted_mode_fails_closed_for_legacy_shared_workspace_routes(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as app_module
    monkeypatch.setattr(app_module, "APP_ENV", "hosted")
    client = TestClient(app_module.app, base_url="https://testserver")
    checks = [
        ("GET", "/api/dashboard/summary"),
        ("GET", "/api/source-data/status"),
        ("GET", "/api/operational/transactions"),
        ("POST", "/api/reconciliation/run"),
        ("POST", "/api/upload/transactions"),
        ("POST", "/api/processing/run"),
        ("GET", "/api/audit/summary"),
        ("POST", "/api/ai-harness/investigate"),
    ]
    for method, path in checks:
        response = client.request(method, path)
        assert response.status_code == 503, (method, path, response.status_code, response.text)
        assert "tenant-scoped storage" in response.json()["detail"]


def test_hosted_mode_keeps_health_auth_and_tenant_routes_reachable(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main as app_module
    monkeypatch.setattr(app_module, "APP_ENV", "hosted")
    client = TestClient(app_module.app, base_url="https://testserver")
    assert client.get("/health").status_code == 200
    assert client.get("/api/auth/oidc/config-status").status_code == 200
    # Tenant route is reachable at the router, but must still require identity.
    response = client.get("/api/tenant-workspace/status")
    assert response.status_code in (401, 403)


def test_hosted_readiness_script_does_not_echo_secret_values():
    script = Path(__file__).resolve().parents[1] / "scripts" / "hosted_readiness.py"
    source = script.read_text(encoding="utf-8")
    assert "Never prints secret values" in source
    assert "print(json.dumps(report, indent=2))" in source
    assert "PLATFORM_SESSION_SECRET" in source
    assert "OIDC discovery check failed" in source
