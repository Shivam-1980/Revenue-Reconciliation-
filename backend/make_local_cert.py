"""Create a local HTTPS certificate for 127.0.0.1 / localhost (self-signed, valid ~2 years).

    python make_local_cert.py            # creates backend/data/certs/eko-local.crt + eko-local.key if missing
    python make_local_cert.py --force    # recreate

Used when EKO_HTTPS=true in backend/.env. Browsers warn about a self-signed certificate until it is trusted:
run trust_local_cert.bat once (adds it to YOUR Windows user's trusted roots; Windows asks you to confirm).
Extra host names or IPs (for a LAN server): EKO_CERT_HOSTS=eko-server,192.168.1.20
"""
import datetime
import ipaddress
import os
import socket
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERT_DIR = Path(__file__).resolve().parent / "data" / "certs"
CERT = CERT_DIR / "eko-local.crt"
KEY = CERT_DIR / "eko-local.key"


def _san():
    names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.IPAddress(ipaddress.ip_address("::1"))]
    try:
        names.append(x509.DNSName(socket.gethostname()))
    except OSError:
        pass
    for host in filter(None, (h.strip() for h in os.getenv("EKO_CERT_HOSTS", "").split(","))):
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    return names


def lan_addresses() -> list[str]:
    """IPv4 addresses of this PC on its networks (used for the certificate and the printed address)."""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    try:                                                    # the address used for the default route (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1)); ip = probe.getsockname()[0]
            if ip not in found and not ip.startswith("127."):
                found.insert(0, ip)
    except OSError:
        pass
    return found


def _covers(cert_path: Path) -> bool:
    """True when the existing certificate already lists every name this PC is reached by."""
    try:
        have = x509.load_pem_x509_certificate(cert_path.read_bytes()).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        have_dns = {str(n.value).lower() for n in have if isinstance(n, x509.DNSName)}
        have_ip = {str(n.value) for n in have if isinstance(n, x509.IPAddress)}
        return all((str(n.value).lower() in have_dns) if isinstance(n, x509.DNSName) else (str(n.value) in have_ip) for n in _san())
    except Exception:
        return False


def ensure_cert(force: bool = False) -> tuple[Path, Path]:
    if CERT.exists() and KEY.exists() and not force and _covers(CERT):
        return CERT, KEY
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Eko SBI Reconciliation (local)"), x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(_san()), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, content_commitment=False, data_encipherment=False, key_agreement=False,
                                         key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return CERT, KEY


if __name__ == "__main__":
    cert, key = ensure_cert(force="--force" in sys.argv)
    print(f"Certificate: {cert}\nPrivate key: {key} (keep private)\nRun trust_local_cert.bat once so the browser stops warning.")
