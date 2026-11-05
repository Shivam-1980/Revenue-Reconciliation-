"""Run this on the OTHER computer to check that it can reach the Revenue Reconciliation data (plain Python 3, nothing to install).

    python check_agent_connection.py --url https://192.168.1.20:8000 --key <the API key> --cacert eko-local.crt

It tells, in plain words, which step works. The key is never printed.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request


def call(url, key, ctx):
    req = urllib.request.Request(url, headers={"X-API-Key": key} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="address printed by start.bat, e.g. https://192.168.1.20:8000")
    ap.add_argument("--key", required=True, help="API key made with create_agent_api_key.py")
    ap.add_argument("--cacert", help="eko-local.crt copied from the PC that runs the app")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    ctx = ssl.create_default_context(cafile=a.cacert) if a.cacert else ssl.create_default_context()
    steps = []

    def step(name, ok, detail=""):
        steps.append(ok); print(("PASS  " if ok else "FAIL  ") + name + (f"  - {detail}" if detail else ""))

    try:
        code, body = call(base + "/health", None, ctx)
        step("1. The PC answers over a locked connection", code == 200 and "healthy" in body, f"answer {code}")
    except Exception as e:
        step("1. The PC answers over a locked connection", False, f"{type(e).__name__}: {e}")
        print("\nNothing else can be tried. Check: the address, that the app is running with EKO_BIND_HOST=0.0.0.0 and EKO_HTTPS=true,\n"
              "that allow_network_access.bat was run as administrator on that PC, and that --cacert is the file from that PC.")
        return 1
    code, _ = call(base + "/api/agent/v1/uploads", None, ctx)
    step("2. Without a key the data is refused", code in (401, 403), f"answer {code}")
    code, body = call(base + "/api/agent/v1/uploads", a.key, ctx)
    rows = None
    if code == 200:
        try: rows = len(json.loads(body).get("items", []))
        except Exception: pass
    step("3. With the key the data can be read", code == 200, f"answer {code}" + (f", {rows} stored files listed" if rows is not None else ""))
    print("\nAll good: this computer can reach the data." if all(steps) else "\nSomething is not right: see the FAIL lines above.")
    return 0 if all(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
