"""Create the first administrator (or another user) for sign-in.

Usage (from the backend folder, with the backend venv's python):
    python create_platform_admin.py --email you@company.com
    python create_platform_admin.py --email ops@company.com --role operator
    python create_platform_admin.py --if-none   (start.bat: only when no user exists yet)

The password is prompted securely and never written to files. Sign-in is e-mail + password
(plus the optional Google button when it is configured).
"""
import argparse
import getpass
import secrets
import sys
import time

from app.platform_security import _db, _password_hash
from app import database
from app.security_core import initialize_security_schema

ROLES = ("super_admin", "org_admin", "operator", "viewer")

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--email")
parser.add_argument("--if-none", action="store_true", help="do nothing when at least one user already exists")
parser.add_argument("--role", choices=ROLES, default="super_admin")
parser.add_argument("--org-id", default="eko")
parser.add_argument("--org-name", default="Eko Bharat Ventures")
args = parser.parse_args()

database.init_schema()
initialize_security_schema()
if args.if_none:
    _conn = _db()
    try:
        if _conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]:
            sys.exit(0)
    finally:
        _conn.close()
    print()
    print("No user exists yet. Create the first administrator account.")
    print("Sign-in is with this e-mail address and the password you choose next.")
    print()
    args.role = "super_admin"
def _valid_email(value):
    return "@" in value and "." in value.split("@")[-1] and " " not in value


email = (args.email or "").strip().lower()
for _ in range(3):
    if _valid_email(email): break
    if email: print("  That is not a valid e-mail address. Example: name@eko.co.in")
    email = input("Administrator e-mail: ").strip().lower()
else:
    print("No valid e-mail address given.", file=sys.stderr); sys.exit(2)

print("The password is not shown while you type (this is normal). Minimum 14 characters.")
for _ in range(3):
    password = getpass.getpass("New password: ")
    if len(password) < 14:
        print(f"  Too short ({len(password)} characters). Please use at least 14 characters."); continue
    if getpass.getpass("Confirm password: ") != password:
        print("  The two passwords did not match. Please try again."); continue
    break
else:
    print("Password was not set after 3 attempts.", file=sys.stderr); sys.exit(2)

conn = _db()
try:
    now = int(time.time())
    if not conn.execute("SELECT id FROM organizations WHERE id=?", (args.org_id,)).fetchone():
        conn.execute("INSERT INTO organizations(id,name,created_at,active) VALUES(?,?,?,1)", (args.org_id, args.org_name, now))
    if conn.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone():
        print(f"A user with e-mail {email!r} already exists.", file=sys.stderr); sys.exit(1)
    conn.execute("INSERT INTO users(id,email,password_hash,role,organization_id,active,created_at) VALUES(?,?,?,?,?,1,?)",
                 (secrets.token_hex(16), email, _password_hash(password), args.role, args.org_id, now))
    conn.commit()
    print(f"Created {args.role} {email!r} in organisation {args.org_id!r}.")
except SystemExit:
    raise
except Exception as exc:
    conn.rollback(); print(f"Could not create user: {exc}", file=sys.stderr); sys.exit(1)
finally:
    conn.close()
