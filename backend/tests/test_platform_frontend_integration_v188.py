from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_uses_cookie_session_and_csrf_not_stored_bearer_tokens():
    # V62.6.206: the HttpOnly session cookie replaces bearer tokens kept in localStorage.
    source = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    auth = (ROOT / "frontend" / "src" / "auth.jsx").read_text(encoding="utf-8")
    assert "installAuthFetch(API_BASE)" in source and "<AuthGate apiBase={API_BASE}>" in source
    assert 'credentials: "include"' in auth and 'headers.set("X-CSRF-Token", csrfToken)' in auth
    assert "localStorage.setItem" not in auth and 'localStorage.getItem("eko_platform_token")' not in source
    assert 'headers.set("X-Eko-Workspace",selectedOrg)' in source
    assert 'platformFetch(`${API_BASE}/api/tenant-workspace/status`)' in source


def test_cors_allows_workspace_selection_header_for_super_admin():
    source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert '"X-Eko-Workspace"' in source


def test_oidc_exchange_serializes_one_time_code_redemption():
    source = (ROOT / "backend" / "app" / "platform_security.py").read_text(encoding="utf-8")
    assert 'SELECT access_token,expires_at FROM oidc_login_codes WHERE code_hash=? FOR UPDATE' in source
    assert 'conn.execute("BEGIN IMMEDIATE")' in source
