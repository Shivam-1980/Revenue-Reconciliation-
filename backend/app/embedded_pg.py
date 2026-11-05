"""Built-in PostgreSQL 16 managed by the app (V62.6.214).

The PostgreSQL binaries come from the pinned ``pgserver`` package (no installer, no admin rights);
the server itself is configured here:

* data directory ``backend/data/pgdata`` (created once with ``initdb``)
* login only with a password (scram-sha-256) that is generated per installation and kept in
  ``backend/data/local_secrets.json`` (or EKO_PG_PASSWORD), never the passwordless "trust" default
* listens on 127.0.0.1 only, fixed port ``EKO_PG_PORT`` (default 54329)
* ``ensure_running()`` starts it if needed and returns the DATABASE_URL; ``stop()`` shuts it down cleanly
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

BACKEND = Path(__file__).resolve().parents[1]
PGDATA = Path(os.getenv("EKO_PGDATA", str(BACKEND / "data" / "pgdata")))
PORT = int(os.getenv("EKO_PG_PORT", "54329"))
SUPERUSER = "eko_app"
DBNAME = "eko_reconciliation"
HOST = "127.0.0.1"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class EmbeddedPostgresError(RuntimeError):
    pass


def _bin() -> Path:
    try:
        from pgserver.postgres_server import POSTGRES_BIN_PATH
    except ImportError as exc:
        raise EmbeddedPostgresError("The built-in PostgreSQL needs the 'pgserver' package (pip install -r backend/requirements.txt).") from exc
    return Path(POSTGRES_BIN_PATH)


def _run(exe: str, *args, check=True, timeout=120, **kw):
    cmd = [str(_bin() / f"{exe}.exe" if sys.platform == "win32" else _bin() / exe), *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW, **kw)
    if check and proc.returncode != 0:
        raise EmbeddedPostgresError(f"{exe} failed ({proc.returncode}): {(proc.stderr or proc.stdout).strip()[:600]}")
    return proc


def password() -> str:
    from app.secret_store import get_secret
    return get_secret("EKO_PG_PASSWORD")


def database_url(db: str = DBNAME) -> str:
    return f"postgresql://{SUPERUSER}:{quote(password(), safe='')}@{HOST}:{PORT}/{db}"


def _init_cluster():
    if (PGDATA / "PG_VERSION").exists():
        return
    PGDATA.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".pw", encoding="utf-8") as handle:
        handle.write(password()); pwfile = handle.name
    try:
        _run("initdb", "-D", PGDATA, "-U", SUPERUSER, "--auth=scram-sha-256", f"--pwfile={pwfile}", "-E", "UTF8", "--no-locale", timeout=300)
    finally:
        os.unlink(pwfile)
    conf = PGDATA / "postgresql.conf"
    conf.write_text(conf.read_text(encoding="utf-8") + f"\nlisten_addresses = '{HOST}'\nport = {PORT}\nlog_min_messages = warning\n"
                    "password_encryption = scram-sha-256\nmax_connections = 60\nshared_buffers = 128MB\n", encoding="utf-8")


def is_running() -> bool:
    return _run("pg_ctl", "-D", PGDATA, "status", check=False).returncode == 0


def _port_owner():
    """(pid, data directory or None) of the process listening on PORT, or None when the port is free."""
    import socket
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex((HOST, PORT)) != 0:
            return None
    try:
        import psutil                                   # installed with pgserver
        # Windows sometimes reports a live listener's status as NONE/CLOSE_WAIT, so the status is not filtered on.
        for conn in psutil.net_connections("tcp"):
            if conn.laddr and conn.laddr.port == PORT and conn.pid:
                cmd = psutil.Process(conn.pid).cmdline()
                datadir = cmd[cmd.index("-D") + 1] if "-D" in cmd[:-1] else None
                return conn.pid, (datadir if Path(cmd[0]).stem.lower() == "postgres" else None)
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            cmd = proc.info["cmdline"] or []
            if (proc.info["name"] or "").lower().startswith("postgres") and "-D" in cmd[:-1]:
                datadir = cmd[cmd.index("-D") + 1]
                pidfile = Path(datadir, "postmaster.pid")
                if pidfile.exists() and str(PORT) in pidfile.read_text(encoding="utf-8").splitlines()[3:4]:
                    return proc.info["pid"], datadir
    except Exception:
        pass
    return -1, None


def _free_port():
    """Another EKO folder's built-in PostgreSQL left running (its backend already closed) holds the fixed port.
    Shut it down cleanly (no data is lost; that folder starts it again when it is launched); refuse anything else."""
    owner = _port_owner()
    if owner is None:
        return
    pid, datadir = owner
    if datadir and Path(datadir, "PG_VERSION").exists() and Path(datadir).resolve() != PGDATA.resolve():
        print(f"Port {PORT} is held by the built-in database of another EKO folder ({datadir}); stopping it cleanly...", flush=True)
        _run("pg_ctl", "-D", datadir, "-m", "fast", "-w", "stop", check=False, timeout=120)
        for _ in range(20):
            if _port_owner() is None:
                return
            time.sleep(0.5)
    raise EmbeddedPostgresError(
        f"Port {PORT} (built-in database) is used by another program (process {pid}"
        + (f", data folder {datadir}" if datadir else "") + "). Close it, or set EKO_PG_PORT in backend\\.env to a free port, then run start.bat again.")


def _ensure_database():
    import psycopg
    for attempt in range(30):
        try:
            with psycopg.connect(database_url("postgres"), autocommit=True, connect_timeout=5) as conn:
                if not conn.execute("select 1 from pg_database where datname=%s", (DBNAME,)).fetchone():
                    conn.execute(f'create database "{DBNAME}" encoding \'UTF8\' template template0')
            return
        except psycopg.OperationalError:
            time.sleep(1)
    raise EmbeddedPostgresError("The built-in PostgreSQL started but did not accept connections.")


def ensure_running() -> str:
    """Start the built-in server if it is not running; return its DATABASE_URL."""
    _init_cluster()
    if not is_running():
        _free_port()
        # A stale lock from a hard stop is cleaned by PostgreSQL itself on start (crash recovery).
        # The server process inherits pg_ctl's handles: never give it a pipe (subprocess would wait for it forever).
        exe = _bin() / ("pg_ctl.exe" if sys.platform == "win32" else "pg_ctl")
        proc = subprocess.run([str(exe), "-D", str(PGDATA), "-l", str(PGDATA / "server.log"), "-w", "-t", "90", "start"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
                              creationflags=CREATE_NO_WINDOW)
        if proc.returncode != 0:
            tail = (PGDATA / "server.log").read_text(encoding="utf-8", errors="replace")[-600:] if (PGDATA / "server.log").exists() else ""
            raise EmbeddedPostgresError(f"The built-in PostgreSQL did not start. Log: {tail}")
    _ensure_database()
    return database_url()


def stop():
    if (PGDATA / "PG_VERSION").exists() and is_running():
        _run("pg_ctl", "-D", PGDATA, "-m", "fast", "-w", "stop", check=False, timeout=120)


def bin_path() -> Path:
    return _bin()
