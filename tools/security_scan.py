"""Check pinned dependencies for known vulnerabilities (Python: pip-audit, JavaScript: npm audit).

    python tools/security_scan.py

Needs internet. pip-audit is installed on demand into the current Python environment. Exit code 1 if anything is found.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd, cwd=ROOT):
    print("$", " ".join(map(str, cmd)))
    return subprocess.run(cmd, cwd=cwd).returncode


def main():
    if run([sys.executable, "-m", "pip", "install", "-q", "pip-audit"]) != 0:
        print("Could not install pip-audit"); return 2
    py = run([sys.executable, "-m", "pip_audit", "-r", "backend/requirements.txt", "--no-deps", "--disable-pip"])
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    js = run([npm, "audit"], cwd=ROOT / "frontend") if npm else 2
    print(f"\nPython: {'clean' if py == 0 else 'VULNERABILITIES FOUND'} | JavaScript: {'clean' if js == 0 else 'VULNERABILITIES FOUND' if js == 1 else 'not checked (npm missing)'}")
    return 0 if py == 0 and js == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
