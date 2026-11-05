"""Encryption at rest (V62.6.214): AES-256-GCM, chunked so multi-hundred-MB files can be handled.

File/blob layout:  b"EKOENC1" | 8-byte random nonce prefix | chunks...
Each chunk:        4-byte big-endian length | AES-GCM ciphertext+tag of up to 4 MiB of plaintext
Nonce per chunk:   prefix (8) + chunk counter (4); associated data = b"\\x01" for the last chunk, b"\\x00" otherwise,
                   so a truncated, reordered or modified file fails to decrypt (it is never silently shortened).

The key is derived (HKDF-SHA256) from ``EKO_ENCRYPTION_KEY`` (environment, required in hosted mode) or from a
random per-installation value in ``backend/data/local_secrets.json``. Losing that key makes encrypted data
unrecoverable: keep a copy of the key (see docs/SECURITY_AND_BACKUP.md).
"""
from __future__ import annotations

import io
import os
import struct
from typing import BinaryIO

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.secret_store import get_secret

MAGIC = b"EKOENC1"
CHUNK = 4 * 1024 * 1024
_NONCE_PREFIX = 8


class DecryptionError(ValueError):
    pass


def _key() -> bytes:
    secret = get_secret("EKO_ENCRYPTION_KEY").encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"eko-sbi-reconciliation-v1", info=b"data-at-rest").derive(secret)


def is_encrypted(head: bytes) -> bool:
    return head[: len(MAGIC)] == MAGIC


def _nonce(prefix: bytes, counter: int) -> bytes:
    return prefix + struct.pack(">I", counter)


def encrypt_stream(src: BinaryIO, dst: BinaryIO) -> int:
    """Encrypt ``src`` into ``dst``; returns the number of plaintext bytes."""
    aes, prefix, total, counter = AESGCM(_key()), os.urandom(_NONCE_PREFIX), 0, 0
    dst.write(MAGIC + prefix)
    block = src.read(CHUNK)
    while True:
        following = src.read(CHUNK)
        last = not following
        ct = aes.encrypt(_nonce(prefix, counter), block, b"\x01" if last else b"\x00")
        dst.write(struct.pack(">I", len(ct)) + ct)
        total += len(block)
        if last:
            return total
        block, counter = following, counter + 1


def decrypt_stream(src: BinaryIO, dst: BinaryIO) -> int:
    head = src.read(len(MAGIC) + _NONCE_PREFIX)
    if not is_encrypted(head) or len(head) != len(MAGIC) + _NONCE_PREFIX:
        raise DecryptionError("Not an encrypted EKO file.")
    aes, prefix, counter, total = AESGCM(_key()), head[len(MAGIC):], 0, 0
    raw = src.read(4)
    while raw:
        if len(raw) != 4:
            raise DecryptionError("The encrypted file is truncated.")
        (length,) = struct.unpack(">I", raw)
        ct = src.read(length)
        following = src.read(4)
        last = not following
        try:
            plain = aes.decrypt(_nonce(prefix, counter), ct, b"\x01" if last else b"\x00")
        except Exception as exc:
            raise DecryptionError("Decryption failed: wrong key, or the data was modified or cut short.") from exc
        dst.write(plain)
        total += len(plain)
        raw, counter = following, counter + 1
    if counter == 0:
        raise DecryptionError("The encrypted file is empty.")
    return total


def encrypt_bytes(data: bytes) -> bytes:
    out = io.BytesIO()
    encrypt_stream(io.BytesIO(data), out)
    return out.getvalue()


def decrypt_bytes(blob: bytes) -> bytes:
    """Decrypt a blob; data written before encryption was introduced (no header) is returned unchanged."""
    if not is_encrypted(blob[: len(MAGIC)]):
        return blob
    out = io.BytesIO()
    decrypt_stream(io.BytesIO(blob), out)
    return out.getvalue()


# --- masking of personal identifiers in database copies --------------------------------------------------
SENSITIVE_KEY_PARTS = ("account", "mobile", "phone", "mail", "aadhaar", "aadhar", "pan_", "card")


def mask_value(value) -> str | None:
    """Keep only the last 4 characters: 123456789012 -> ****9012."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.startswith("****"):
        return text or None
    return "****" + text[-4:] if len(text) > 4 else "****"


def mask_record(record: dict) -> dict:
    return {k: (mask_value(v) if any(part in str(k).lower() for part in SENSITIVE_KEY_PARTS) else v) for k, v in record.items()}
