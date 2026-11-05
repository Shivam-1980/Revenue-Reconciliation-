import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.audit_service import list_runs


def test_audit_run_history_contains_no_nan_values():
    rows = list_runs(20)
    # A clean first launch legitimately has no prior runs.
    if not rows:
        return
    for row in rows:
        assert all(not (isinstance(v, float) and v != v) for v in row.values())
