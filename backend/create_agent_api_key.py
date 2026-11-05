"""Create, list or revoke API keys for the super agent (or any other machine client).

Usage (from the backend folder, with the backend venv's python):
    python create_agent_api_key.py --name super-agent                      # full access (scope *), 90 days
    python create_agent_api_key.py --name reporting-bot --scopes read --days 30
    python create_agent_api_key.py --list
    python create_agent_api_key.py --revoke <key_id>

Scopes: read (all GET data), write (upload/run/archive/sync), admin (users, keys, audit log), * (everything).
The key is printed once and only its SHA-256 hash is stored. Keep it in the agent's secret store.
Signed-in administrators can do the same through POST /api/auth/api-keys.
"""
import argparse
import hashlib
import json
import secrets
import sys
import time

from app import database
from app.platform_security import _db, record_audit
from app.auth_scopes import API_SCOPES
from app.security_core import initialize_security_schema

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--name")
group.add_argument("--list", action="store_true")
group.add_argument("--revoke", metavar="KEY_ID")
parser.add_argument("--scopes", nargs="+", default=["*"], choices=sorted(API_SCOPES))
parser.add_argument("--days", type=int, default=90, help="validity in days (1-365)")
parser.add_argument("--org-id", default="eko")
args = parser.parse_args()

database.init_schema()
initialize_security_schema()
conn = _db()
actor = {"sub": "cli:create_agent_api_key", "org": args.org_id}
try:
    if args.list:
        now = int(time.time())
        for r in conn.execute("SELECT id,name,scopes_json,expires_at,revoked FROM api_keys ORDER BY created_at DESC").fetchall():
            state = "revoked" if r["revoked"] else ("expired" if int(r["expires_at"]) <= now else "active")
            print(f"{r['id']}  {r['name']:<24} scopes={','.join(json.loads(r['scopes_json']))}  "
                  f"expires={time.strftime('%Y-%m-%d', time.localtime(int(r['expires_at'])))}  {state}")
        sys.exit(0)
    if args.revoke:
        if not conn.execute("SELECT id FROM api_keys WHERE id=?", (args.revoke,)).fetchone():
            print("No such key.", file=sys.stderr); sys.exit(1)
        conn.execute("UPDATE api_keys SET revoked=1 WHERE id=?", (args.revoke,)); conn.commit()
        record_audit(actor, "api_key.revoked", {"key_id": args.revoke})
        print(f"Revoked {args.revoke}."); sys.exit(0)
    if not 1 <= args.days <= 365:
        print("--days must be between 1 and 365.", file=sys.stderr); sys.exit(2)
    if not conn.execute("SELECT id FROM organizations WHERE id=?", (args.org_id,)).fetchone():
        print(f"Organisation {args.org_id!r} does not exist yet. Create the first administrator with start.bat first.", file=sys.stderr); sys.exit(1)
    raw = "eko_" + secrets.token_urlsafe(32)
    key_id, now, scopes = secrets.token_hex(12), int(time.time()), sorted(set(args.scopes))
    conn.execute("INSERT INTO api_keys(id,name,key_hash,organization_id,scopes_json,expires_at,revoked,created_at) VALUES(?,?,?,?,?,?,0,?)",
                 (key_id, args.name.strip(), hashlib.sha256(raw.encode()).hexdigest(), args.org_id, json.dumps(scopes), now + args.days * 86400, now))
    conn.commit()
    record_audit(actor, "api_key.created", {"key_id": key_id, "name": args.name.strip(), "scopes": scopes, "days": args.days})
    print(f"Created API key {key_id} ({args.name.strip()}), scopes={','.join(scopes)}, valid {args.days} days.")
    print("Copy it now; it will not be shown again:\n")
    print(raw)
finally:
    conn.close()
