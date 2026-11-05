from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_has_security_headers_and_stays_compatible():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'healthy'}
    assert response.headers.get('x-content-type-options') == 'nosniff'
    assert response.headers.get('x-frame-options') == 'DENY'


def test_api_version_reports_safety_baseline():
    response = client.get('/api/version')
    assert response.status_code == 200
    assert response.json()['version'] == '62.6.216-ui-security-speed'


def test_oversized_request_is_rejected_before_route_execution(monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module, 'MAX_UPLOAD_MB', 1)
    response = client.post('/api/workspace/clear-current-data', headers={'content-length': str(2 * 1024 * 1024)})
    assert response.status_code == 413
    assert '1 MB limit' in response.json()['detail']


def test_workspace_reset_rejects_remote_client(monkeypatch):
    from starlette.testclient import TestClient as StarletteTestClient
    # Simulate a remote client address; ensure reset cannot delete the local workspace.
    from starlette.requests import Request
    endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', None) == '/api/workspace/clear-current-data')
    scope = {'type': 'http', 'method': 'POST', 'path': '/api/workspace/clear-current-data', 'headers': [], 'client': ('203.0.113.9', 12345), 'server': ('testserver', 80), 'scheme': 'http', 'query_string': b'', 'root_path': '', 'http_version': '1.1'}
    request = Request(scope)
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        endpoint(request)
    assert exc.value.status_code == 403
