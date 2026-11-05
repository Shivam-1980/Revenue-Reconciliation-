"""Make a small folder to hand to the other computer: the certificate, the checker and the address (V62.6.216).

    python make_agent_kit.py [--port 8000] [--out ..\agent_kit]

The API key is NOT included: make it with create_agent_api_key.py and give it separately.
"""
import argparse
import shutil
from pathlib import Path

from make_local_cert import CERT, ensure_cert, lan_addresses

ap = argparse.ArgumentParser()
ap.add_argument("--port", default="8000")
ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "agent_kit"))
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
ensure_cert()
shutil.copyfile(CERT, out / "eko-local.crt")
shutil.copyfile(Path(__file__).resolve().parent.parent / "check_agent_connection.py", out / "check_agent_connection.py")
addrs = [f"https://{ip}:{a.port}" for ip in lan_addresses()] or [f"https://<this PC's address>:{a.port}"]
(out / "README.txt").write_text(
    "Revenue Reconciliation - connect from this computer\n\n"
    "Address(es) of the app: " + ", ".join(addrs) + "\n"
    "Certificate: eko-local.crt (make this computer trust it; do not turn the check off)\n"
    "Key: given to you separately (header  X-API-Key: <key>)\n\n"
    "Check the connection:\n  python check_agent_connection.py --url " + addrs[0] + " --key <key> --cacert eko-local.crt\n\n"
    "Then use the guide docs\AGENT_API.md (list uploads, read rows page by page, results).\n", encoding="utf-8")
print("Kit written to", out)
for x in addrs: print("  address:", x)
