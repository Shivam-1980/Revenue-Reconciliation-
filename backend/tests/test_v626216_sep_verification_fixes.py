"""Faults found when the September files were verified end to end (V62.6.216)."""
import io
import pandas as pd
from app.services import reconciliation_engine as eng


def _run(tx_rows, bc_rows):
    tx = pd.DataFrame(tx_rows, columns=["transaction_id", "csp_id", "transaction_type", "amount", "status", "transaction_date"])
    bc = pd.DataFrame(bc_rows, columns=["csp_id", "transaction_type", "report_base", "actual_commission"])
    out = eng.reconcile_transactions(tx, bc)
    return out[0] if isinstance(out, tuple) else out


def test_money_transfer_and_fund_transfer_do_not_share_one_bank_actual():
    tx = [("1", "C1", "Money Transfer", 2000, "Success", "2026-09-02")] * 1
    tx += [("2", "C1", "Money Transfer", 3000, "Success", "2026-09-03"), ("3", "C1", "Fund Transfer", 4000, "Success", "2026-09-04")]
    bc = [("C1", "MONEY TRANSFER", 2, 30.0), ("C1", "FUNDTRANSFER - HOME", 1, 10.0)]
    r = _run(tx, bc)
    mt = r[r["transaction_type"] == "MONEY TRANSFER"].iloc[0]
    ft = r[r["transaction_type"] == "FUND TRANSFER"].iloc[0]
    assert float(mt["actual_commission"]) == 30.0
    assert float(ft["actual_commission"]) == 10.0
