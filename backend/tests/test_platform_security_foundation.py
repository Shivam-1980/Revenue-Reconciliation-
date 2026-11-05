import os
import tempfile
from pathlib import Path


def test_password_hash_is_salted_and_verifies(monkeypatch, tmp_path):
    from app import platform_security as ps
    monkeypatch.setattr(ps, 'DB_PATH', tmp_path / 'platform.sqlite3')
    first = ps._password_hash('a-long-test-password')
    second = ps._password_hash('a-long-test-password')
    assert first != second
    assert ps._verify_password('a-long-test-password', first)
    assert not ps._verify_password('wrong-password', first)


def test_token_roundtrip_and_expiry(monkeypatch, tmp_path):
    from app import platform_security as ps
    monkeypatch.setattr(ps, 'DB_PATH', tmp_path / 'platform.sqlite3')
    monkeypatch.setattr(ps, 'TOKEN_SECRET', 'test-secret-that-is-long-enough')
    class Row(dict):
        def __getitem__(self, key): return super().__getitem__(key)
    row = Row(id='u1', email='admin@example.com', role='org_admin', organization_id='org1')
    token = ps._issue_token(row)
    claims = ps.verify_token(token)
    assert claims['sub'] == 'u1'
    assert claims['org'] == 'org1'
    assert claims['role'] == 'org_admin'


def test_platform_db_creates_org_user_audit_tables(monkeypatch, tmp_path):
    from app import platform_security as ps
    monkeypatch.setattr(ps, 'DB_PATH', tmp_path / 'platform.sqlite3')
    conn = ps._db()
    try:
        tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'organizations', 'users', 'audit_events'} <= tables
    finally:
        conn.close()
