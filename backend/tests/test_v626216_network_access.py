"""Reaching the app from another computer (V62.6.216): only over HTTPS, and the certificate names the network address."""
import importlib
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
serve = importlib.import_module("serve")


def test_loopback_is_always_allowed():
    for host in ("127.0.0.1", "localhost", "::1"):
        assert serve.network_problem(host, False, False) is None


def test_network_address_over_plain_http_is_refused():
    assert "EKO_HTTPS=true" in serve.network_problem("0.0.0.0", False, False)
    assert "EKO_HTTPS=true" in serve.network_problem("192.168.1.20", False, False)


def test_network_address_is_allowed_with_https_or_a_proxy():
    assert serve.network_problem("0.0.0.0", True, False) is None
    assert serve.network_problem("0.0.0.0", False, True) is None


def test_certificate_is_remade_when_it_lacks_a_network_address(tmp_path, monkeypatch):
    mlc = importlib.import_module("make_local_cert")
    monkeypatch.setattr(mlc, "CERT_DIR", tmp_path); monkeypatch.setattr(mlc, "CERT", tmp_path / "c.crt"); monkeypatch.setattr(mlc, "KEY", tmp_path / "c.key")
    monkeypatch.delenv("EKO_CERT_HOSTS", raising=False)
    first = mlc.CERT.__class__(mlc.ensure_cert()[0]).read_bytes()
    assert mlc.ensure_cert()[0].read_bytes() == first                    # unchanged while it still covers everything
    monkeypatch.setenv("EKO_CERT_HOSTS", "192.168.1.20,eko-server")
    second = mlc.ensure_cert()[0].read_bytes()
    assert second != first and mlc._covers(mlc.CERT)                     # now names the address other computers use
    assert mlc.ensure_cert()[0].read_bytes() == second


def test_lan_addresses_are_ipv4_and_not_loopback():
    mlc = importlib.import_module("make_local_cert")
    for ip in mlc.lan_addresses():
        assert ip.count(".") == 3 and not ip.startswith("127.")
