"""Organisation-scoped storage path helpers.
Only use this helper for new tenant-aware features; legacy local pipeline paths are untouched.
"""
import os, re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
STORAGE_ROOT = Path(os.getenv("TENANT_STORAGE_ROOT", str(BACKEND_DIR / "data" / "tenants"))).resolve()
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")

def workspace_dir(organization_id: str) -> Path:
    org = str(organization_id or "").strip()
    if not _ID_RE.fullmatch(org):
        raise ValueError("Invalid organization ID")
    path = (STORAGE_ROOT / org).resolve()
    if path == STORAGE_ROOT or STORAGE_ROOT not in path.parents:
        raise ValueError("Workspace path escapes tenant storage root")
    path.mkdir(parents=True, exist_ok=True)
    return path

def resolve_workspace_file(organization_id: str, relative_path: str) -> Path:
    base = workspace_dir(organization_id)
    candidate = (base / relative_path).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError("Workspace file path escapes organisation directory")
    return candidate
