import pandas as pd
from app.services.reconciliation_engine import reconcile_social_security_direct


def test_august_pmjjby_pmsby_direct_reconciliation_uses_exact_csp_and_period_rates():
    source = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"PMJJBY", "count":2, "premium":436, "period":"2026-08"},
        {"csp_id":"1A850001", "transaction_type":"PMSBY", "count":3, "premium":20, "period":"2026-08"},
        {"csp_id":"Gursewak Gursewak", "transaction_type":"PMJJBY", "count":2, "premium":436, "period":"2026-08"},
    ])
    commission = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"PMJJBY", "report_base":2, "actual_commission":60},
        {"csp_id":"1A850001", "transaction_type":"PMSBY", "report_base":3, "actual_commission":3},
        {"csp_id":"1A850002", "transaction_type":"PMJJBY", "report_base":1, "actual_commission":30},
    ])
    result = reconcile_social_security_direct(source, commission, period="2026-08")
    assert result["available"] is True
    assert result["total"]["source_transactions"] == 5
    assert result["total"]["bc_transactions"] == 6
    assert result["total"]["expected_commission"] == 63
    assert result["total"]["actual_commission"] == 93
    assert result["total"]["commission_difference_bc_minus_expected"] == 30
    assert all(r["csp_id"] != "GURSEWAK GURSEWAK" for r in result["rows"])
    assert any(r["csp_id"] == "1A850002" and r["status"] == "BC EXCESS" for r in result["rows"])


def test_direct_reconciliation_applies_november_pmjjby_rate_by_period():
    source = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"PMJJBY", "count":4, "premium":342, "period":"2026-11"},
    ])
    commission = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"PMJJBY", "report_base":4, "actual_commission":90},
    ])
    result = reconcile_social_security_direct(source, commission, period="2026-11")
    assert result["total"]["expected_commission"] == 90
    assert result["total"]["actual_commission"] == 90
    assert result["total"]["commission_difference_bc_minus_expected"] == 0
