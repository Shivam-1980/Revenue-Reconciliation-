from fastapi.testclient import TestClient
from app.main import app


def test_passbook_printing_get_does_not_expose_internal_rate_helper_as_route():
    client = TestClient(app)
    response = client.get('/api/reconciliation/passbook-printing')
    # With missing sources this endpoint should return an application-level JSON
    # status (normally 200 with available=false), not FastAPI's 422 for the
    # helper's internal arguments.
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    assert 'available' in body or 'status' in body
