"""HTTPS: hosted mode refuses plain http, proxy header trust is explicit, local certificate is correct."""
import datetime
import importlib.util
import ipaddress
from pathlib import Path

import pytest
from cryptography import x509
from fastapi.testclient import TestClient

import make_local_cert
from app import main

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(main, "APP_ENV", "hosted")
    monkeypatch.delenv("EKO_BEHIND_PROXY", raising=False)


def test_hosted_mode_rejects_plain_http_for_api_and_redirects_pages(hosted):
    http = TestClient(main.app, base_url="http://eko.example")
    r = http.get("/api/version")
    assert r.status_code == 400 and r.json()["detail"] == "HTTPS is required."
    r = http.get("/", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"].startswith("https://eko.example")
    assert http.get("/health").status_code == 200                       # load-balancer probes may use http
    https = TestClient(main.app, base_url="https://eko.example")
    assert https.get("/api/version").status_code == 200
    assert "max-age=31536000" in https.get("/api/version").headers["strict-transport-security"]


def test_forwarded_proto_is_only_trusted_behind_a_declared_proxy(hosted, monkeypatch):
    client = TestClient(main.app, base_url="http://127.0.0.1")
    assert client.get("/api/version", headers={"X-Forwarded-Proto": "https"}).status_code == 400   # spoofable: ignored by default
    monkeypatch.setenv("EKO_BEHIND_PROXY", "true")
    assert client.get("/api/version", headers={"X-Forwarded-Proto": "https"}).status_code == 200
    assert client.get("/api/version", headers={"X-Forwarded-Proto": "http"}).status_code == 400


def test_local_mode_keeps_plain_http_working():
    assert TestClient(main.app, base_url="http://127.0.0.1").get("/api/version").status_code == 200


def test_local_certificate_covers_localhost_and_loopback_and_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(make_local_cert, "CERT_DIR", tmp_path)
    monkeypatch.setattr(make_local_cert, "CERT", tmp_path / "c.crt")
    monkeypatch.setattr(make_local_cert, "KEY", tmp_path / "c.key")
    monkeypatch.setenv("EKO_CERT_HOSTS", "eko-server,192.168.1.20")
    cert_path, key_path = make_local_cert.ensure_cert()
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName) and "eko-server" in san.get_values_for_type(x509.DNSName)
    ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    assert {"127.0.0.1", "::1", "192.168.1.20"} <= ips
    assert cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc) > datetime.timedelta(days=700)
    assert not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert b"BEGIN RSA PRIVATE KEY" in key_path.read_bytes()
    before = cert_path.read_bytes()
    make_local_cert.ensure_cert()
    assert cert_path.read_bytes() == before                              # existing certificate is reused
    make_local_cert.ensure_cert(force=True)
    assert cert_path.read_bytes() != before


def test_certificates_keys_backups_and_database_files_never_ship():
    spec = importlib.util.spec_from_file_location("package_release", ROOT / "tools" / "package_release.py")
    pr = importlib.util.module_from_spec(spec); spec.loader.exec_module(pr)
    for rel in ("backend/data/certs/eko-local.key", "backend/data/certs/eko-local.crt", "backend/data/pgdata/base/1/1259",
                "backend/data/backups/eko_backup_20261029_180000.ekobak", "backend/data/pii_masked_v1.txt"):
        assert pr.is_excluded(Path(rel)), rel
    for rel in ("backend/serve.py", "backend/make_local_cert.py", "backend/backup_database.py", "deploy/Caddyfile", "trust_local_cert.bat", "frontend/vite.config.js"):
        assert not pr.is_excluded(Path(rel)), rel


def test_batch_launcher_uses_scheme_variables_and_stays_crlf():
    bat = (ROOT / "start.bat").read_bytes()
    assert bat.count(b"\n") == bat.count(b"\r\n")
    text = bat.decode("ascii")
    assert "env_flag.py" in text and 'set "API=%SCHEME%://127.0.0.1:8000"' in text and "curl.exe -k" in text
    assert "http://127.0.0.1:8000" not in text and "http://127.0.0.1:5173" not in text
