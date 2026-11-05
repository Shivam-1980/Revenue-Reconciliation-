import pandas as pd


def test_bc_typo_imps_fundtranfer_maps_to_imps_transfer():
    from app.services.reconciliation_engine import resolve_transaction_type
    assert resolve_transaction_type("IMPS FUNDTRANFER") == "IMPS TRANSFER"


def test_imps_fundtranfer_bc_commission_joins_source_group():
    from app.services.reconciliation_engine import reconcile_transactions
    transactions = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"IMPS FUND TRANSFER", "amount":2000, "transaction_date":"2026-08-12"}
    ])
    commission = pd.DataFrame([
        {"csp_id":"1A850001", "transaction_type":"IMPS FUNDTRANFER", "report_base":1, "actual_commission":27.0}
    ])
    rules = pd.DataFrame(columns=["rule_id", "transaction_type", "rate", "rate_type"])
    out = reconcile_transactions(transactions, commission, rate_rules=rules)
    row = out[(out["csp_id"] == "1A850001") & (out["successful_transactions"] == 1)]
    assert not row.empty
    assert pd.to_numeric(row.iloc[0]["actual_commission"], errors="coerce") == 27.0
