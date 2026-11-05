"""Shared test setup.

Every /api route now requires authentication. Business-logic tests run as a signed-in
super_admin by replacing the request authenticator; tests marked ``real_auth`` exercise
the real password + session enforcement instead. Production code has no
authentication bypass flag.
"""
import os
import tempfile
from pathlib import Path

_TEST_STATE = Path(tempfile.mkdtemp(prefix="eko_test_security_"))
os.environ.setdefault("EKO_SECRETS_PATH", str(_TEST_STATE / "local_secrets.json"))
# Tests never touch the project database: the platform/business DB is a throwaway SQLite file.
os.environ["PLATFORM_DB_PATH"] = str(_TEST_STATE / "platform.sqlite3")
os.environ.pop("DATABASE_URL", None)
os.environ["EKO_XLSX_WORKERS"] = "0"      # no worker processes in ordinary tests; the parallel scan has its own tests
os.environ["EKO_DATABASE"] = "sqlite"   # tests use SQLite or an explicit test PostgreSQL, never the built-in server

import pytest  # noqa: E402

from app import security_core  # noqa: E402
from app.services import db_sync  # noqa: E402

TEST_PRINCIPAL = {"sub": "test-admin", "email": "test-admin@example.invalid", "role": "super_admin", "org": None, "via": "test"}


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: run with real authentication enforcement (no test principal)")


@pytest.fixture(autouse=True)
def _signed_in_principal(request, monkeypatch):
    security_core.rate_limiter.reset()
    # Background workspace->DB syncs are triggered by API calls; tests run sync explicitly instead.
    monkeypatch.setattr(db_sync, "sync_in_background", lambda *a, **k: None)
    if request.node.get_closest_marker("real_auth"):
        return
    monkeypatch.setattr(security_core, "authenticate_request", lambda req: dict(TEST_PRINCIPAL))


@pytest.fixture(autouse=True)
def _no_release_marker_left_behind():
    """The workspace-reset endpoint writes a release marker next to the app; a clean tree has none."""
    marker = Path(__file__).resolve().parents[2] / ".eko_reconciliation_initialized_version"
    yield
    marker.unlink(missing_ok=True)
