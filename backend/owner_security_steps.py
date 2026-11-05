"""Walks the owner through the three steps software cannot decide for you (V62.6.216).

    python owner_security_steps.py            (or double-click owner_security_steps.bat in the project folder)

1. Keep a copy of the secret key somewhere else (without it saved months and backups cannot be opened).
2. Keep the backups away from this disk (OneDrive folder, external or network drive).
3. Check that disk encryption (BitLocker) is on.
Nothing is changed until you type the folder and confirm. The key itself is never printed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ENV = HERE / ".env"


def set_env_value(text, name, value):
    """Return the .env text with `name=value` set (replaces an existing line, otherwise appends)."""
    lines = text.splitlines()
    out, done = [], False
    for ln in lines:
        if ln.split("=", 1)[0].strip() == name and not ln.lstrip().startswith("#"):
            if not done:
                out.append(f"{name}={value}"); done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{name}={value}")
    return "\n".join(out) + "\n"


def ask(question, default=""):
    shown = f" [{default}]" if default else ""
    answer = input(f"{question}{shown}: ").strip().strip('"')
    return answer or default


def yes(question):
    return input(f"{question} (y/n): ").strip().lower() in {"y", "yes"}


def run_backup(*args):
    return subprocess.run([sys.executable, str(HERE / "backup_database.py"), *args], cwd=HERE, capture_output=True, text=True, env={**os.environ})


def main():
    from dotenv import load_dotenv
    load_dotenv(ENV, override=False)
    from app.services import security_posture as sp
    print("\n=== Owner security steps ===\n")
    state = {c["id"]: c for c in sp.posture()["checks"]}
    for cid in ("key_copy", "backup_location", "disk_encryption"):
        c = state[cid]; print(f"  [{c['status'].upper():7}] {c['title']}: {c['detail']}")

    print("\n--- Step 1: copy of the secret key ---")
    if state["key_copy"]["status"] == "ok":
        print("Already done.")
    elif yes("Save a copy of the key now?"):
        where = ask("Folder or file for the copy (a USB drive or a private folder, NOT only on this PC)", str(Path.home() / "OneDrive" / "EkoKeyCopy"))
        out = Path(where); out = out if out.suffix else out / "eko_keys.txt"
        res = run_backup("export-key", "--out", str(out))
        ok = res.returncode == 0 and out.exists() and "EKO_ENCRYPTION_KEY" in json.loads(out.read_text(encoding="utf-8") or "{}")
        print(("Saved: " if ok else "Could not save: ") + (str(out) if ok else (res.stderr or res.stdout).strip()[:300]))
        if ok:
            ok_disk, why = sp.backup_is_off_disk(str(out.parent))
            print("  " + ("Good: " if ok_disk else "Note: ") + why + ("" if ok_disk else ". Also copy this file to a USB drive and keep it somewhere safe."))

    print("\n--- Step 2: backups away from this disk ---")
    if state["backup_location"]["status"] == "ok":
        print("Already done.")
    elif yes("Choose a backup folder now?"):
        where = ask("Backup folder (OneDrive folder, external drive or network path)", str(Path.home() / "OneDrive" / "EkoBackups"))
        off, why = sp.backup_is_off_disk(where)
        print(("Good: " if off else "Not good enough: ") + why)
        if (off or yes("This is still the same disk. Use it anyway?")) and yes(f"Write EKO_BACKUP_DIR={where} to backend\.env and make a backup there now?"):
            Path(where).mkdir(parents=True, exist_ok=True)
            ENV.write_text(set_env_value(ENV.read_text(encoding="utf-8") if ENV.exists() else "", "EKO_BACKUP_DIR", where), encoding="utf-8")
            env = {**os.environ, "EKO_BACKUP_DIR": where}
            res = subprocess.run([sys.executable, str(HERE / "backup_database.py"), "create"], cwd=HERE, capture_output=True, text=True, env=env)
            print((res.stdout or res.stderr).strip()[-300:])
            print("Saved. Restart the app (start.bat) so it uses the new folder for its daily backups.")

    print("\n--- Step 3: disk encryption (BitLocker) ---")
    c = state["disk_encryption"]
    print(c["detail"])
    if c["status"] != "ok" and os.name == "nt" and yes("Open the Windows page where you can turn it on?"):
        os.startfile("ms-settings:deviceencryption")
    print("\nDone. Run it again any time to see the current state.")


if __name__ == "__main__":
    main()
