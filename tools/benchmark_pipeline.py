"""Benchmark the upload -> reconciliation -> dashboard pipeline on synthetic data.

Usage (from the project root, with the backend venv's python):
    python tools/benchmark_pipeline.py --rows 10000 50000 --format csv xlsx [--workdir DIR]

The backend is copied into a throwaway work directory first, so benchmarking never
touches the real app/data folder. Synthetic CSP IDs (SYN...) and transactions are
generated deterministically; no real or prior-month data is used.
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


class PeakRSS:
    """Sample process RSS in a background thread (psutil if available)."""

    def __init__(self):
        try:
            import psutil
            self._proc = psutil.Process()
        except ImportError:
            self._proc = None
        self.peak = 0

    def __enter__(self):
        self._stop = False
        self.peak = self._rss()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _rss(self):
        return self._proc.memory_info().rss if self._proc else 0

    def _run(self):
        while not self._stop:
            self.peak = max(self.peak, self._rss())
            time.sleep(0.02)

    def __exit__(self, *exc):
        self._stop = True
        self._thread.join()


def synthetic_sources(rows, period="2026-09", n_csp=None, seed=7):
    rng = np.random.default_rng(seed)
    mapping = pd.read_csv(ROOT / "backend" / "app" / "data" / "transaction_type_mapping_master.csv").fillna("")
    types = mapping.loc[mapping["status"].str.upper() == "EXACT", "source_transaction_type"].drop_duplicates().tolist()
    n_csp = n_csp or max(50, rows // 200)
    csps = [f"SYN{i:05d}" for i in range(n_csp)]
    start = pd.Timestamp(f"{period}-01")
    days = start.days_in_month
    tx = pd.DataFrame({
        "Reference Number": [f"SYN-{i:09d}" for i in range(rows)],
        "CSP Code": rng.choice(csps, rows),
        "Type of Transaction": rng.choice(types, rows),
        "Amount": rng.integers(100, 20000, rows),
        "Date": (start + pd.to_timedelta(rng.integers(0, days * 86400, rows), unit="s")).strftime("%Y-%m-%d %H:%M:%S"),
        "Status": "SUCCESS",
    })
    cm = (tx.groupby(["CSP Code", "Type of Transaction"]).size().rename("Count").reset_index()
          .rename(columns={"Type of Transaction": "Transaction Type"}))
    cm["Commission"] = (cm["Count"] * 5).astype(float)
    cm["Month"] = start.strftime("%b %Y")
    return tx, cm


def encode(df, fmt):
    buf = io.BytesIO()
    if fmt == "csv":
        df.to_csv(buf, index=False)
        return buf.getvalue(), "text/csv"
    df.to_excel(buf, index=False)
    return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def prepare_workdir(base: Path) -> Path:
    backend = base / "backend"
    if backend.exists():
        shutil.rmtree(backend)
    shutil.copytree(ROOT / "backend", backend, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "reconciliation_history"))
    subprocess.run([sys.executable, "reset_initial_data.py"], cwd=backend, check=True, stdout=subprocess.DEVNULL)
    return backend


def _api_key_headers():
    """Every /api route requires authentication: use a full-scope API key in the throwaway benchmark DB."""
    import hashlib
    import secrets
    import time as _time
    from sqlalchemy import text
    from app import database
    database.init_schema()
    raw = "eko_bench_" + secrets.token_urlsafe(24)
    now = int(_time.time())
    with database.get_engine().begin() as conn:
        if not conn.execute(text("SELECT 1 FROM organizations WHERE id='bench'")).first():
            conn.execute(text("INSERT INTO organizations(id,name,created_at,active) VALUES('bench','Benchmark',:n,1)"), {"n": now})
        conn.execute(text("INSERT INTO api_keys(id,name,key_hash,organization_id,scopes_json,expires_at,revoked,created_at) "
                          "VALUES(:i,'benchmark',:h,'bench','[\"*\"]',:e,0,:n)"),
                     {"i": raw[-16:], "h": hashlib.sha256(raw.encode()).hexdigest(), "e": now + 86400, "n": now})
    return {"X-API-Key": raw}


_THREAD_PROFILES = []
RESPONSE_DIR = None     # set by --save-responses: each GET response is kept so two code versions can be compared


def _profile_worker_threads():
    """The API runs sync endpoints in a thread pool, which a profiler on the calling thread never sees: profile inside it."""
    import cProfile
    import functools
    import starlette.concurrency as sc
    import fastapi.routing as fr
    original = sc.run_in_threadpool

    async def profiled(func, *args, **kwargs):
        @functools.wraps(func)
        def inner(*a, **k):
            prof = cProfile.Profile()
            prof.enable()
            try:
                return func(*a, **k)
            finally:
                prof.disable()
                _THREAD_PROFILES.append(prof)
        return await original(inner, *args, **kwargs)
    sc.run_in_threadpool = fr.run_in_threadpool = profiled


def run_case(rows, fmt, profile_steps=(), profile_dir=None):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import db_sync
    # Time the reconciliation engine alone; the background DB sync is benchmarked separately.
    db_sync.sync_in_background = lambda *a, **k: None

    tx, cm = synthetic_sources(rows)
    tx_bytes, tx_type = encode(tx, fmt)
    cm_bytes, cm_type = encode(cm, fmt)
    client = TestClient(app, headers=_api_key_headers())
    client.post("/api/workspace/clear-current-data")
    steps = [
        ("upload_transactions", "post", "/api/upload/transactions", {"files": {"file": (f"tx.{fmt}", tx_bytes, tx_type)}}),
        ("upload_commission", "post", "/api/upload/commission", {"files": {"file": (f"cm.{fmt}", cm_bytes, cm_type)}}),
        ("status", "get", "/api/reconciliation/status", {}),
        ("run_reconciliation", "post", "/api/reconciliation/run", {}),
        ("csp_results", "get", "/api/reconciliation/csp", {}),
        ("exceptions", "get", "/api/reconciliation/exceptions", {}),
        ("dashboard_summary", "get", "/api/dashboard/summary", {}),
        ("archive_snapshot", "post", "/api/reconciliation/history/archive-current", {}),
    ]
    result = {"rows": rows, "format": fmt, "tx_file_mb": round(len(tx_bytes) / 1e6, 2), "commission_groups": len(cm), "steps": {}}
    for name, method, url, kwargs in steps:
        del _THREAD_PROFILES[:]
        with PeakRSS() as mem:
            t0 = time.perf_counter()
            resp = getattr(client, method)(url, **kwargs)
            elapsed = time.perf_counter() - t0
        if name in profile_steps and _THREAD_PROFILES:
            import pstats
            stats = pstats.Stats(_THREAD_PROFILES[0])
            for extra in _THREAD_PROFILES[1:]:
                stats.add(extra)
            stats.dump_stats(str(Path(profile_dir or ".") / f"profile_{name}_{rows}.prof"))
        result["steps"][name] = {"seconds": round(elapsed, 2), "peak_rss_mb": round(mem.peak / 1e6), "status": resp.status_code}
        if method == "get":
            import hashlib
            result["steps"][name]["response_sha256"] = hashlib.sha256(resp.content).hexdigest()
            if RESPONSE_DIR:
                RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
                (RESPONSE_DIR / f"{rows}_{name}.json").write_bytes(resp.content)
        if name == "run_reconciliation":
            result["run_summary"] = {k: v for k, v in resp.json().items() if not isinstance(v, (list, dict))}
        if name == "csp_results" and resp.status_code == 200:
            result["csp_rows"] = len(resp.json())
    result["total_seconds"] = round(sum(s["seconds"] for s in result["steps"].values()), 2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, nargs="+", default=[10000, 50000])
    ap.add_argument("--format", nargs="+", default=["csv"], choices=["csv", "xlsx"])
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--database", choices=["sqlite", "embedded"], default="sqlite",
                    help="embedded = the built-in PostgreSQL, started in the throwaway work directory on --pg-port (never the app's own port)")
    ap.add_argument("--pg-port", type=int, default=54399)
    ap.add_argument("--profile", nargs="*", default=[], help="step names to profile with cProfile")
    ap.add_argument("--profile-dir", default=None)
    ap.add_argument("--save-responses", default=None, help="directory for the GET responses of each case")
    args = ap.parse_args()

    base = Path(args.workdir or tempfile.mkdtemp(prefix="eko_bench_"))
    backend = prepare_workdir(base)
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    os.environ["PLATFORM_DB_PATH"] = str(backend / "data" / "bench_platform.sqlite3")
    os.environ["EKO_SECRETS_PATH"] = str(backend / "data" / "bench_secrets.json")
    os.environ.pop("DATABASE_URL", None)
    os.environ["EKO_DATABASE"] = args.database
    if args.database == "embedded":
        os.environ["EKO_PG_PORT"] = str(args.pg_port)
        os.environ["EKO_PGDATA"] = str(backend / "data" / "bench_pgdata")

    if args.profile:
        _profile_worker_threads()
    if args.save_responses:
        global RESPONSE_DIR
        RESPONSE_DIR = Path(args.save_responses)
    results = []
    for fmt in args.format:
        for rows in args.rows:
            res = run_case(rows, fmt, args.profile, args.profile_dir)
            results.append(res)
            print(json.dumps(res), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
    if args.database == "embedded":
        from app import embedded_pg
        embedded_pg.stop()


if __name__ == "__main__":
    main()
