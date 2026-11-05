from app.api import upload


def test_active_period_fallback_requires_single_month(monkeypatch):
    monkeypatch.setattr(upload, "load_metadata", lambda: {"transactions": {"period_start": "2026-09-01", "period_end": "2026-09-30"}})
    assert upload._active_single_month_period() == "2026-09"


def test_active_period_fallback_rejects_multimonth_source(monkeypatch):
    monkeypatch.setattr(upload, "load_metadata", lambda: {"transactions": {"period_start": "2026-09-01", "period_end": "2026-10-31"}})
    assert upload._active_single_month_period() is None


def test_active_period_fallback_rejects_undated_source(monkeypatch):
    monkeypatch.setattr(upload, "load_metadata", lambda: {"transactions": {"period_start": None, "period_end": None}})
    assert upload._active_single_month_period() is None
