"""Build a clean release ZIP with a single project root.

Usage (from the project root):
    python tools/package_release.py [output_dir] [root_folder_name]

Runtime state, caches, dependencies and one-off developer scripts are excluded so
an extracted release always starts from a clean, month-agnostic state.
"""
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIR_NAMES = {
    "__pycache__", ".pytest_cache", "node_modules", "dist", ".vite", ".venv", "venv", ".git", "dev_outbox", "certs", "pgdata", "backups",
}
EXCLUDED_FILE_NAMES = {
    ".eko_reconciliation_initialized_version",
    "platform.sqlite3",  # recreated empty by platform_security.initialize_platform_db()
    "build_audit_report.py",  # one-off developer script with machine-specific paths
    "local_secrets.json",  # per-installation signing/session secrets (generated on first start)
    ".env",  # real SMTP/database credentials; only *.example templates ship
    ".access_restricted", "pii_masked_v1.txt", "migrated_to_postgresql.txt", "frontend_runtime.log",
    "backend_runtime.log", "backend_diagnostics.log",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".zip", ".env", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".pem", ".key", ".crt", ".ekobak"}
# Period data and generated results must never ship; only permanent masters may.
EXCLUDED_DATA_DIRS = {"transactions", "commissions", "processing", "reconciliation_history", "csp_geography", "audit"}
DATA_ROOT = Path("backend") / "app" / "data"


def is_excluded(rel: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    if rel.name in EXCLUDED_FILE_NAMES or rel.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if rel.name.startswith("~$"):                    # Office lock files of documents someone has open
        return True
    try:
        data_rel = rel.relative_to(DATA_ROOT)
    except ValueError:
        return False
    if data_rel.parts and data_rel.parts[0] in EXCLUDED_DATA_DIRS:
        return True
    # Current-period uploads/outputs are named latest_*; the rate master and the
    # permanent rule workbook are rebuilt/preserved by reset_initial_data.py.
    if data_rel.name.startswith("latest_") and data_rel.parts[0] not in {"rate_master", "expected_commission_rule"}:
        return True
    # upload_metadata.json is a clean template; startup has failed without it before.
    return data_rel.name in {"reconciliation_cache.csv", "reconciliation_cache_meta.json"}


def release_files(root: Path = ROOT):
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root)
            if not is_excluded(rel):
                yield rel


def build(output_dir: Path, root_name: str = ROOT.name) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{root_name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in release_files():
            zf.write(ROOT / rel, (Path(root_name) / rel).as_posix())
    with zipfile.ZipFile(target) as zf:
        bad = zf.testzip()
        if bad:
            raise SystemExit(f"ZIP integrity failed at {bad}")
        roots = {name.split("/", 1)[0] for name in zf.namelist()}
        if roots != {root_name}:
            raise SystemExit(f"Expected one project root, found {sorted(roots)}")
        print(f"Wrote {target} ({len(zf.namelist())} files, root={root_name})")
    return target


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent
    build(out, sys.argv[2] if len(sys.argv) > 2 else ROOT.name)
