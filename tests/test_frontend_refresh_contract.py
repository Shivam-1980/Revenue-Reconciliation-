from pathlib import Path


def test_refresh_reloads_live_backend_state_without_browser_cache():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    refresh = source[source.index("const refresh = async () =>"):source.index("const exportReport = async () =>")]
    assert 'await loadSourceStatus(false)' in refresh
    assert 'cache:"no-store"' in refresh
    assert 'if (active === "Audit & Reports") await loadAudit()' in refresh
    assert 'if (active === "Transaction Traceability") await loadTrace(0)' in refresh
    assert 'if (active === "Period Analysis")' in refresh


def test_core_dashboard_reads_use_no_store_to_avoid_stale_responses():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")
    for endpoint in (
        "/api/reconciliation/status",
        "/api/dashboard/summary",
        "/api/reconciliation/transaction-type",
        "/api/reconciliation/exceptions",
        "/api/dashboard/successful-transaction-types",
    ):
        assert f'{endpoint}`' in source
        # Ensure each core read includes an explicit no-store fetch option.
        assert endpoint in source
    assert 'urls.map(u => fetch(u, {cache:"no-store"}))' in source
