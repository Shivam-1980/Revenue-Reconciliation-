"""Rules taken from the SBI 'Updated Commission Structure 01.04.2025' PDF (V62.6.216)."""
from pathlib import Path
import pandas as pd
from app.services import reconciliation_engine as eng
from app.services.rate_master import build_rate_master_from_workbook, apply_confirmed_remittance_reference_rules, apply_sbi_pdf_schedule_rules

BOOK = Path(__file__).resolve().parents[1] / "app" / "data" / "expected_commission_rule" / "latest.xlsx"


def _rules():
    rules, _ = build_rate_master_from_workbook(BOOK.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    return apply_sbi_pdf_schedule_rules(apply_confirmed_remittance_reference_rules(rules))


def _calc(label, amounts, channel="RURAL"):
    n = len(amounts)
    tx = pd.DataFrame({"transaction_id": [str(i) for i in range(n)], "csp_id": ["C1"] * n, "transaction_type": [label] * n, "amount": amounts,
                       "status": ["Success"] * n, "transaction_date": ["2026-09-02"] * n, "channel": [channel] * n})
    bc = pd.DataFrame({"csp_id": ["C1"], "transaction_type": ["CASH WITHDRAWAL"], "report_base": [1], "actual_commission": [1.0], "channel": [channel]})
    out = eng.reconcile_transactions(tx, bc, _rules())
    out = out[0] if isinstance(out, tuple) else out
    return out[out["transaction_type"] == label.upper()].iloc[0]


def test_generic_schedules_are_confirmed_and_pdf_missing_flat_rates_are_gone():
    r = _rules()
    assert set(r.loc[r["rule_id"].astype(str).str.match(r"^CM0(10|12|13|19|20|51)(-|$)"), "rule_status"]) == {"CONFIRMED"}
    assert not r["rule_id"].isin(["RM-EC-17", "RM-EC-18"]).any()          # Rs 1 acquirer / Rs 15 YONO: Excel only, not in the SBI PDF
    for t in ("AEPS ACQUIRER WITHDRAWAL", "DEBIT CARD ONUS", "DEBIT CARD OFFUS", "YONO CASH"):
        assert (r["transaction_type"] == t).sum() == 8


def test_aeps_onus_withdrawal_follows_the_cash_withdrawal_schedule_and_is_verified():
    row = _calc("AEPS ONUS Withdrawal", [2000, 12000])
    assert float(row["expected_commission"]) == 10.0 + 17.0
    assert float(row["verified_expected_commission"]) == 27.0


def test_aeps_acquirer_withdrawal_is_a_cash_withdrawal_not_rs_1():
    assert float(_calc("AEPS OFFUS Withdrawal", [2000])["expected_commission"]) == 10.0


def test_money_transfer_is_paid_on_the_non_home_remittance_cash_schedule():
    row = _calc("Money Transfer", [2000, 12000, 100000][:2])
    assert float(row["expected_commission"]) == 5.0 + 10.0               # 0.25% (min 2, max 8) ; Rs 10 slab, rural
