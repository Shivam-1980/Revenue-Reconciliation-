"""Per-installation secrets (signing keys, database password, encryption key) without heavy imports.

Order: environment variable, else ``backend/data/local_secrets.json`` (random value created on first use).
In hosted/production mode a secret must come from the environment.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SECRETS_PATH = Path(os.getenv("EKO_SECRETS_PATH", str(BACKEND_DIR / "data" / "local_secrets.json")))
HOSTED = os.getenv("APP_ENV", "local").strip().lower() in {"production", "hosted"}
_lock = threading.Lock()


def get_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value and not value.lower().startswith(("replace", "change", "your-")):
        return value
    with _lock:
        data = {}
        if SECRETS_PATH.exists():
            try:
                data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        if not data.get(name):
            if HOSTED:
                raise RuntimeError(f"{name} must be set in the environment in hosted/production mode.")
            data[name] = secrets.token_urlsafe(48)
            SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = SECRETS_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, SECRETS_PATH)
            restrict_to_current_user(SECRETS_PATH)
        return data[name]


def restrict_to_current_user(path: Path, recursive: bool = False) -> bool:  # `recursive` kept for callers; children inherit
    """Best effort: only the current user, SYSTEM and Administrators may open ``path`` (folder or file).

    Windows: icacls with inheritance removed. Elsewhere: chmod 700/600. Returns True on success; a failure
    (for example on a drive without permission support) never stops the app.
    """
    path = Path(path)
    try:
        if os.name != "nt":
            path.chmod(0o700 if path.is_dir() else 0o600)
            return True
        who = subprocess.run(["whoami"], capture_output=True, text=True, timeout=15, creationflags=0x08000000).stdout.strip()
        flag = "(OI)(CI)F" if path.is_dir() else "F"
        cmd = ["icacls", str(path), "/inheritance:r", "/grant:r", f"{who}:{flag}", f"*S-1-5-18:{flag}", f"*S-1-5-32-544:{flag}"]
        return subprocess.run(cmd, capture_output=True, timeout=300, creationflags=0x08000000).returncode == 0
    except Exception:
        return False
