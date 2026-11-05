import os, sys, tempfile
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def test_tenant_workspace_path_isolated_and_traversal_rejected(tmp_path, monkeypatch):
    from app.services import tenant_storage
    monkeypatch.setattr(tenant_storage, "STORAGE_ROOT", tmp_path.resolve())
    a=tenant_storage.workspace_dir("org_a")
    b=tenant_storage.workspace_dir("org_b")
    assert a != b and a.parent == tmp_path and b.parent == tmp_path
    try:
        tenant_storage.resolve_workspace_file("org_a", "../../secret.csv")
    except ValueError:
        pass
    else:
        raise AssertionError("tenant traversal must be rejected")

def test_tenant_reconciliation_worker_job_type_is_supported_in_source():
    from app.services import platform_worker
    source=Path(platform_worker.__file__).read_text()
    assert "job['job_type'] == 'reconciliation'" in source
    assert "job['job_type'] == 'report_export'" in source
    assert "reconcile_transactions(tx, cm, rules)" in source
