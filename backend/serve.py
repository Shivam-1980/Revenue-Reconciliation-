"""Run the backend with automatic restart and a crash log (V62.6.213).

    python serve.py

Starts uvicorn on 127.0.0.1:8000. If the server process ever stops unexpectedly (a crash, a killed
process), it is started again after 2 seconds, so the dashboard keeps working. Everything the server
prints is also written to ``backend_runtime.log`` in the project folder, including native crash
tracebacks (``-X faulthandler``), so the reason for a stop can always be found.

Close the window or press Ctrl+C to stop the backend for good.
"""
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
LOG = BACKEND.parent / "backend_runtime.log"
MAX_RESTARTS = 8            # more than this within WINDOW seconds means a start-up problem: stop instead of looping
WINDOW = 120
MAX_LOG_BYTES = 5 * 1024 * 1024
PORT = os.getenv("EKO_PORT", "8000")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def network_problem(host, https, proxy):
    """None when it is safe to listen on `host`; otherwise a plain-words reason (V62.6.216).

    Reaching the app from another computer (the other agent, a colleague) means listening on a network address.
    That is only allowed with HTTPS (or behind your own TLS proxy), so passwords, keys and data never travel unlocked."""
    if host in LOOPBACK or https or proxy:
        return None
    return (f"EKO_BIND_HOST={host} would open the app to the network over plain HTTP. Set EKO_HTTPS=true in backend\.env "
            "(or EKO_BEHIND_PROXY=true behind your own HTTPS proxy), then start again.")


def _flag(name):
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env", override=False)
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _stamp(message):
    return f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"


def _log(handle, message):
    line = _stamp(message)
    print(line, flush=True)
    handle.write(line + "\n"); handle.flush()


def _pump(stream, handle):
    for raw in iter(stream.readline, b""):
        text = raw.decode("utf-8", "replace")
        sys.stdout.write(text); sys.stdout.flush()
        handle.write(text); handle.flush()


def _embedded_db():
    """Start the built-in PostgreSQL when EKO_DATABASE=embedded (the same switch the app reads)."""
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env", override=False)
    return os.getenv("EKO_DATABASE", "sqlite").strip().lower() == "embedded" and not os.getenv("DATABASE_URL", "").strip()


def _stop_db(handle, use_pg):
    if use_pg:
        try:
            from app import embedded_pg
            embedded_pg.stop()
            _log(handle, "Built-in PostgreSQL stopped.")
        except Exception as exc:
            _log(handle, f"Could not stop the built-in PostgreSQL cleanly: {exc}")


def main():
    sys.path.insert(0, str(BACKEND))
    use_pg = _embedded_db()
    https = _flag("EKO_HTTPS")
    host = (os.getenv("EKO_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1")
    problem = network_problem(host, https, _flag("EKO_BEHIND_PROXY"))
    if problem:
        print(problem, file=sys.stderr)
        return 2
    cert = key = None
    if https:
        from make_local_cert import ensure_cert, lan_addresses
        if host not in LOOPBACK:                  # the certificate must name the address other computers will type
            extra = [h for h in ([host] if host not in {"0.0.0.0", "::"} else lan_addresses()) if h]
            os.environ["EKO_CERT_HOSTS"] = ",".join(filter(None, [os.getenv("EKO_CERT_HOSTS", "")] + extra))
        cert, key = ensure_cert()
    data_dir = BACKEND / "data"
    marker = data_dir / ".access_restricted"
    if not marker.exists():                       # once: only your Windows user (and SYSTEM/Administrators) can open the data folder
        data_dir.mkdir(exist_ok=True)
        try:
            from app.secret_store import restrict_to_current_user
            restricted = restrict_to_current_user(data_dir, recursive=True)
        except Exception as exc:                   # never stop the backend from starting over a permissions helper
            restricted = False
            print(f"Could not restrict the data folder: {exc}", file=sys.stderr)
        if restricted:
            marker.write_text("Access to this folder is limited to the current user.\n", encoding="utf-8")
    if LOG.exists() and LOG.stat().st_size > MAX_LOG_BYTES:
        LOG.replace(LOG.with_suffix(".log.old"))
    starts = []
    with LOG.open("a", encoding="utf-8") as handle:
        while True:
            now = time.time()
            starts = [t for t in starts if now - t < WINDOW] + [now]
            if len(starts) > MAX_RESTARTS:
                _log(handle, f"Backend stopped {MAX_RESTARTS} times within {WINDOW} s; not restarting again. See the lines above.")
                return 1
            if use_pg:
                try:
                    from app import embedded_pg
                    embedded_pg.ensure_running()          # also brings the database back if it was stopped
                except Exception as exc:
                    _log(handle, f"Built-in PostgreSQL could not start: {exc}")
                    time.sleep(3)
                    continue
            _log(handle, f"Starting backend on {'https' if https else 'http'}://{'127.0.0.1' if host in {'0.0.0.0', '::'} else host}:{PORT}" + (f" (restart #{len(starts) - 1})" if len(starts) > 1 else ""))
            if host not in LOOPBACK:
                from make_local_cert import lan_addresses
                _log(handle, "Other computers reach it at: " + ", ".join(f"{'https' if https else 'http'}://{a}:{PORT}" for a in (lan_addresses() if host in {"0.0.0.0", "::"} else [host])))
            cmd = [sys.executable, "-X", "faulthandler", "-m", "uvicorn", "app.main:app", "--host", host, "--port", PORT, "--log-level", "info"]
            if https:
                cmd += ["--ssl-certfile", str(cert), "--ssl-keyfile", str(key)]
            if _flag("EKO_BEHIND_PROXY"):
                cmd += ["--proxy-headers", "--forwarded-allow-ips", os.getenv("EKO_PROXY_IPS", "127.0.0.1")]
            proc = subprocess.Popen(cmd, cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
            pump = threading.Thread(target=_pump, args=(proc.stdout, handle), daemon=True); pump.start()
            try:
                code = proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill()
                _log(handle, "Backend stopped by the user.")
                _stop_db(handle, use_pg)
                return 0
            pump.join(timeout=2)
            if code == 0:
                _log(handle, "Backend exited normally (code 0).")
                _stop_db(handle, use_pg)
                return 0
            _log(handle, f"Backend stopped unexpectedly (exit code {code}); restarting in 2 seconds.")
            time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
