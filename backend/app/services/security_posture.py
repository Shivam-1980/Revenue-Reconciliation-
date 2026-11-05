"""Plain-language security checklist: what is protected, and what only the owner can still do (V62.6.215).

Every check returns status ok | action | unknown plus one sentence on what to do. Nothing here changes any setting.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
DATA = BACKEND / "data"
KEY_EXPORT_MARKER = DATA / "key_exported.txt"


def _check(cid, title, status, detail, fix=None):
    return {"id": cid, "title": title, "status": status, "detail": detail, "fix": fix}


def _flag(name, default=False):
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _powershell(command, timeout=20):
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return ""
    try:
        return subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def _bitlocker_from_shell(drive):
    """'on' | 'off' | None from the Windows shell property System.Volume.BitLockerProtection (1 = on, 0 = off, 2 = suspended)."""
    if os.name != "nt":
        return None
    out = _powershell(f"(New-Object -ComObject Shell.Application).NameSpace('{drive}\').Self.ExtendedProperty('System.Volume.BitLockerProtection')")
    return {"1": "on", "0": "off"}.get(out.strip())


def physical_disk(path):
    """Number of the physical disk that holds `path` (C:, D: and E: are often partitions of ONE disk), or None when unknown."""
    if os.name != "nt":
        return None
    drive = Path(path).resolve().drive
    if not drive or drive.startswith("\\\\"):
        return None
    out = _powershell(f"(Get-Partition -DriveLetter '{drive[0]}' -ErrorAction Stop).DiskNumber")
    return int(out) if out.strip().isdigit() else None


def backup_is_off_disk(backup_dir, data_dir=None):
    """(True/False, why). A OneDrive folder or a network path is a second copy; another drive letter counts only when it is another physical disk."""
    if not backup_dir:
        return False, "no separate backup folder is set"
    text = str(backup_dir)
    if "onedrive" in text.lower():
        return True, "the folder is inside OneDrive"
    if text.startswith("\\\\"):
        return True, "the folder is on the network"
    here = physical_disk(data_dir or DATA)
    there = physical_disk(backup_dir)
    if here is not None and there is not None:
        return (here != there), ("it is on a different physical disk" if here != there else f"drive letters differ but both are on physical disk {here}")
    return (Path(text).resolve().drive.lower() != Path(data_dir or DATA).resolve().drive.lower()), "another drive letter (could not read the physical disk)"


def _bitlocker():
    """BitLocker status of the drive that holds the data. Reading it needs administrator rights, so 'unknown' is common."""
    title = "Disk encryption (BitLocker)"
    if os.name != "nt":
        return _check("disk_encryption", title, "unknown", "Not Windows: check your operating system's disk encryption.")
    drive = (DATA.resolve().drive or "C:").rstrip("\\")
    shell = _bitlocker_from_shell(drive)            # readable without administrator rights
    if shell == "on":
        return _check("disk_encryption", title, "ok", f"Drive {drive} is BitLocker-protected.")
    if shell == "off":
        return _check("disk_encryption", title, "action", f"Drive {drive} is not encrypted. The current month's working files are plain CSV on it.",
                      "Windows Settings > Privacy & security > Device encryption (or BitLocker) > turn on.")
    exe = shutil.which("manage-bde")
    if exe:
        try:
            low = subprocess.run([exe, "-status", drive], capture_output=True, text=True, timeout=20).stdout.lower()
            if "protection on" in low:
                return _check("disk_encryption", title, "ok", f"Drive {drive} is BitLocker-protected.")
            if "protection off" in low:
                return _check("disk_encryption", title, "action", f"Drive {drive} is not encrypted. The current month's working files are plain CSV on it.",
                              "Windows Settings > Privacy & security > Device encryption (or BitLocker) > turn on.")
        except Exception:
            pass
    return _check("disk_encryption", title, "unknown", "Could not be read without administrator rights.",
                  "Check Windows Settings > Privacy & security > Device encryption: it should be On.")


def posture() -> dict:
    from app import database
    from app.services import backup
    checks = []
    try:
        engine = database.get_engine().dialect.name
    except Exception:
        engine = "unknown"
    checks.append(_check("database", "Database", "ok" if engine == "postgresql" else "action",
                         "PostgreSQL with a password, reachable only from this PC." if engine == "postgresql" else f"Using {engine}: a single file without a password.",
                         None if engine == "postgresql" else "Set EKO_DATABASE=embedded in backend/.env and restart."))
    https = _flag("EKO_HTTPS")
    checks.append(_check("https", "HTTPS (encrypted connection)", "ok" if https else "action",
                         "Traffic between the browser and the app is encrypted." if https else "Plain HTTP on this PC: acceptable only while nobody else can reach the port.",
                         None if https else "Set EKO_HTTPS=true in backend/.env, restart with start.bat, then run trust_local_cert.bat once."))
    exported = KEY_EXPORT_MARKER.exists()
    checks.append(_check("key_copy", "Encryption key kept elsewhere", "ok" if exported else "action",
                         "A copy of the key was exported." if exported else "Saved months and backups cannot be opened if local_secrets.json is lost.",
                         None if exported else "python backup_database.py export-key --out <USB drive or private folder>\\eko_keys.txt"))
    custom = os.getenv("EKO_BACKUP_DIR", "").strip()
    off_disk, why = backup_is_off_disk(custom)
    checks.append(_check("backup_location", "Backups stored away from this disk", "ok" if off_disk else "action",
                         f"Backups go to {custom} ({why})." if off_disk else ("Backups are on the same disk as the data: a disk failure loses both." if not custom else f"Backups go to {custom}, but {why}: a disk failure still loses both."),
                         None if off_disk else "Run owner_security_steps.bat and choose a OneDrive folder or an external / network drive (backups are encrypted)."))
    try:
        items = backup.list_backups()
        newest = max((float(i.get("modified") or 0) for i in items), default=0)
        age_days = (time.time() - newest) / 86400 if newest else None
    except Exception:
        age_days = None
    fresh = age_days is not None and age_days <= 2
    checks.append(_check("backup_fresh", "Recent backup", "ok" if fresh else "action",
                         "Latest backup is %.1f day(s) old." % age_days if age_days is not None else "No backup found.",
                         None if fresh else "Run: python backup_database.py create"))
    restricted = (DATA / ".access_restricted").exists()
    checks.append(_check("data_folder", "Data folder limited to your Windows user", "ok" if restricted else "action",
                         "Only you, SYSTEM and Administrators can open backend/data." if restricted else "Applied when the backend starts through serve.py / start.bat.",
                         None if restricted else "Start the app with start.bat."))
    checks.append(_bitlocker())
    return {"checks": checks, "ok": sum(c["status"] == "ok" for c in checks), "action": sum(c["status"] == "action" for c in checks),
            "unknown": sum(c["status"] == "unknown" for c in checks), "checked_at": int(time.time())}
