"""Create, check and restore encrypted database backups.

Usage (from the backend folder, with the backend venv's python):
    python backup_database.py create                  # new backup now
    python backup_database.py list
    python backup_database.py verify eko_backup_20261029_180000.ekobak
    python backup_database.py restore eko_backup_20261029_180000.ekobak            # into an empty database
    python backup_database.py restore <file> --force   # replaces everything in the current database
    python backup_database.py export-key --out D:\\safe\\eko_keys.txt   # keep the key separate from the backups!

Backups go to backend/data/backups (or EKO_BACKUP_DIR) and are encrypted: without the key in
backend/data/local_secrets.json (or EKO_ENCRYPTION_KEY) they cannot be opened.
"""
import argparse
import json
import sys
from pathlib import Path

from app import database
from app.secret_store import get_secret
from app.services import backup

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = parser.add_subparsers(dest="cmd", required=True)
sub.add_parser("create"); sub.add_parser("list")
v = sub.add_parser("verify"); v.add_argument("file")
r = sub.add_parser("restore"); r.add_argument("file"); r.add_argument("--force", action="store_true")
k = sub.add_parser("export-key"); k.add_argument("--out", required=True)
args = parser.parse_args()

try:
    if args.cmd == "export-key":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"EKO_ENCRYPTION_KEY": get_secret("EKO_ENCRYPTION_KEY"), "note": "Needed to open every .ekobak backup and saved month. Store away from the backups."}, indent=2), encoding="utf-8")
        try:                                                  # lets the security checklist show that a copy exists
            from app.services.security_posture import KEY_EXPORT_MARKER
            KEY_EXPORT_MARKER.parent.mkdir(parents=True, exist_ok=True)
            KEY_EXPORT_MARKER.write_text("A copy of the encryption key was exported.\n", encoding="utf-8")
        except Exception:
            pass
        print(f"Key written to {out}. Keep this file private and separate from the backups.")
        sys.exit(0)
    database.init_schema()
    if args.cmd == "create":
        info = backup.create_backup("manual")
        print(f"Created {info['file']}: {info['rows']:,} rows, {info['size_bytes']/1e6:.1f} MB in {info['seconds']} s\nFolder: {backup.backup_dir()}")
    elif args.cmd == "list":
        for b in backup.list_backups():
            print(f"{b['file']}  {b['size_bytes']/1e6:8.1f} MB")
        print(f"({len(backup.list_backups())} backup(s) in {backup.backup_dir()})")
    elif args.cmd == "verify":
        res = backup.verify_backup(args.file)
        print(("OK" if res["ok"] else "DAMAGED"), f"- {res['rows']:,} rows, created {res['created_utc']}, engine {res['engine']}", *res["problems"], sep="\n  " if res["problems"] else " ")
        sys.exit(0 if res["ok"] else 1)
    elif args.cmd == "restore":
        res = backup.restore_backup(args.file, force=args.force)
        print(f"Restored {res['rows']:,} rows from {res['restored_from']}.")
except Exception as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
