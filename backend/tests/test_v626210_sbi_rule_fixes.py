"""SBI commission rules vs the engine (V62.6.210 audit).

An independent calculator written straight from the SBI Consolidated Commission Master wording
(exact Decimal arithmetic, half-up to the paisa) is compared with calculate_expected at every slab
boundary, including paise amounts that used to fall between slabs.
"""
from decimal import ROUND_HALF_UP, Decimal as D
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.services.rate_master import calculate_expected

RULES = pd.read_csv(Path(__file__).resolve().parents[1] / "app" / "data" / "rate_master" / "latest_rate_master.csv")


def r2(x):
    return x.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def slabbed(pct, lo, hi_r, hi_u, s2, s3, s4, min_amount):
    def f(a, ch):
        i = 0 if ch == "RURAL" else 1
        if a < min_amount or a > 30000:
            return None  # SBI schedule: min ₹100 where documented; no rule above ₹30,000
        if a <= 10000:
            return r2(min(max(a * D(pct) / 100, D(lo)), D(hi_r if ch == "RURAL" else hi_u)))
        return D(s2[i] if a <= 15000 else s3[i] if a <= 20000 else s4[i])
    return f


CW = slabbed("0.5", 3, 15, 17, (17, 20), (20, 22), (23, 25), 100)          # Cash withdrawal (rows 12-15)
CD = slabbed("0.25", 2, 8, 10, (10, 12), (12, 15), (15, 18), 100)          # Cash deposit / remittance cash (16-19, 22-25)
FTH = slabbed("1", 3, 10, 12, (12, 15), (15, 17), (18, 20), 0)              # Remittance transfer, home branch (26-29)
ORACLE = {"CASH WITHDRAWAL": CW, "AEPS ONUS WITHDRAWAL": CW, "CASH DEPOSIT": CD, "AEPS ONUS DEPOSIT": CD,
          "MATM ONUS DEPOSIT": CD, "LOAN DEPOSIT": CD, "FUNDTRANSFER - NON HOME": CD, "FUNDTRANSFER - HOME": FTH,
          "AEPS ONUS FUNDTRANSFER - HOME": FTH, "MATM ONUS FUNDSTRANSFER - HOME": FTH}
AMOUNTS = ["1", "99.99", "100", "101", "333", "999.99", "1000", "1005", "1999", "3333", "4285.72", "9999.99", "10000",
           "10000.01", "10000.5", "10000.99", "10001", "12000", "15000", "15000.5", "15001", "20000", "20000.5", "20001",
           "25000", "30000", "30000.01"]


def _engine(rule_type, channel, amounts):
    tx = pd.DataFrame({"rule_type": rule_type, "csp_id": "C1", "channel": channel, "amount": amounts, "transaction_date": "2026-09-15"})
    out, _ = calculate_expected(tx, RULES)
    return [None if pd.isna(v) else r2(D(str(v))) for v in out["expected_commission"]]


@pytest.mark.parametrize("rule_type", sorted(ORACLE))
@pytest.mark.parametrize("channel", ["RURAL", "URBAN"])
def test_engine_matches_sbi_workbook_at_every_boundary(rule_type, channel):
    got = _engine(rule_type, channel, AMOUNTS)
    want = [ORACLE[rule_type](D(a), channel) for a in AMOUNTS]
    diffs = [(a, str(w), str(g)) for a, w, g in zip(AMOUNTS, want, got) if w != g]
    assert not diffs, diffs


def test_paise_amounts_no_longer_fall_between_slabs():
    # Previously ₹10,000.50 matched neither "up to 10,000" nor ">= 10,001" and earned nothing.
    assert _engine("CASH WITHDRAWAL", "RURAL", ["10000.5", "15000.5", "20000.5"]) == [D("17.00"), D("20.00"), D("23.00")]
    assert _engine("CASH DEPOSIT", "URBAN", ["10000.5", "15000.5", "20000.5"]) == [D("12.00"), D("15.00"), D("18.00")]
    # Whole-rupee boundaries are unchanged.
    assert _engine("CASH WITHDRAWAL", "RURAL", ["10000", "10001"]) == [D("15.00"), D("17.00")]


def test_half_paisa_rounds_up_not_down():
    # 0.5% of 1,999 = 9.995 -> ₹10.00 (float error used to give ₹9.99).
    assert _engine("CASH WITHDRAWAL", "RURAL", ["1999"]) == [D("10.00")]
    assert _engine("STDR OPEN", "URBAN", ["1999"]) == [D("10.00")]
    assert _engine("CASH DEPOSIT", "RURAL", ["1002"]) == [D("2.51")]  # 2.505 -> 2.51


def test_imps_fee_based_commission():
    # IMPS cash: 80% of fee (0.70%, min 10, max 35), commission min 8 max 28; IMPS transfer: 50% (fee max 100), min 5 max 50.
    assert _engine("IMPS CASH", "", ["100", "2000", "5000", "5000.01"]) == [D("8.00"), D("11.20"), D("28.00"), None]
    assert _engine("IMPS TRANSFER", "", ["100", "4000", "30000"]) == [D("5.00"), D("14.00"), D("50.00")]


def test_tab_cap_is_always_the_sbi_rule_not_the_upload(monkeypatch, tmp_path):
    from app.api import upload
    from app.main import app
    monkeypatch.setattr(upload, "TAB_COUNTS", tmp_path / "tab.csv")
    monkeypatch.setattr(upload, "TAB_META", tmp_path / "tab_meta.json")
    monkeypatch.setattr(upload, "clear_cache", lambda: None)
    monkeypatch.setattr(upload, "save_source", lambda *a, **k: None, raising=False)
    csv = ("Month,CSP Code,TAB Financial Transactions,Monthly Cap\n"
           "2026-09,1A850001,400,5000\n2026-09,1A850002,10,1000\n").encode()
    r = TestClient(app).post("/api/upload/tab-incentive", files={"file": ("tab_sep.csv", BytesIO(csv), "text/csv")})
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    assert v["monthly_cap"] == 1000.0 and v["source_monthly_cap_rows_ignored"] == 1 and v["warnings"]
    saved = pd.read_csv(tmp_path / "tab.csv", dtype={"csp_id": str}).set_index("csp_id")
    assert saved.loc["1A850001", "expected_incentive"] == 1000.0   # 400 x ₹5 = 2,000 capped at the SBI ₹1,000
    assert saved.loc["1A850002", "expected_incentive"] == 50.0


def test_bbps_utility_commission_is_the_workbook_amount_per_bill():
    # Business decision 2026-10-29: "80% of CCF (Rs. 4/-)" / "(Rs. 12/-)" -> Rs 4 / Rs 12 per bill.
    assert _engine("BBPS - ELECTRICITY", "", ["250", "1000", "1000.01", "4500"]) == [D("4.00"), D("4.00"), D("12.00"), D("12.00")]
    from app.services.rate_master import build_rate_master_from_workbook, apply_confirmed_remittance_reference_rules
    wb = Path(__file__).resolve().parents[1] / "app" / "data" / "expected_commission_rule" / "latest.xlsx"
    rebuilt, _ = build_rate_master_from_workbook(wb.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    rebuilt = apply_confirmed_remittance_reference_rules(rebuilt).set_index("rule_id")
    assert float(rebuilt.loc["RM-EC-37", "rate"]) == 4.0 and float(rebuilt.loc["RM-EC-38", "rate"]) == 12.0


def test_expected_revenue_uses_only_rates_from_the_sbi_workbook():
    # Debit Card ONUS Rs 14 / OFFUS Rs 13 exist only in an older Excel, not in SBI_Expected_Commission_Rule.xlsx.
    from app.services.rate_master import build_rate_master_from_workbook, apply_confirmed_remittance_reference_rules
    wb = Path(__file__).resolve().parents[1] / "app" / "data" / "expected_commission_rule" / "latest.xlsx"
    rebuilt, _ = build_rate_master_from_workbook(wb.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    rebuilt = apply_confirmed_remittance_reference_rules(rebuilt)
    assert not rebuilt["rule_status"].astype(str).str.upper().str.contains("EXCEL ONLY").any()
    assert not set(rebuilt["transaction_type"]) & {"DEBIT CARD ONUS", "DEBIT CARD OFFUS"}
    # V62.6.216: the SBI PDF has no line for these; they are cash withdrawals (item 4), the Excel-only Rs 14 / 13 / 15 / 1 are not used.
    assert _engine("DEBIT CARD ONUS", "RURAL", ["1000"]) == [D("5.00")]          # 0.50%, min Rs 3
    assert _engine("YONO CASH", "RURAL", ["1000"]) == [D("5.00")]
    assert _engine("AEPS ACQUIRER WITHDRAWAL", "URBAN", ["500"]) == [D("3.00")]  # 0.50% = 2.50, min Rs 3


def test_dfs_rows_show_csp_name_from_sheet_then_bc(monkeypatch, tmp_path):
    from app.api import upload
    tx, cm, sup = tmp_path / "tx", tmp_path / "cm", tmp_path / "sup"
    for d in (tx, cm, sup): d.mkdir()
    pd.DataFrame({"csp_id": ["1A850001", "1A850002"], "csp_name": ["Asha Devi", ""], "slab": ["SLAB-1", "SLAB-2"],
                  "expected_incentive": [1200.0, 1500.0], "transaction_type": "DFS PRIORITIES INCENTIVE", "period": "2026-09",
                  "source_file": "dfs.xlsx"}).to_csv(sup / "dfs.csv", index=False)
    pd.DataFrame({"csp_id": ["1A850001", "1A850002", "1A850003"], "csp_name": ["ASHA DEVI", "RAM PRASAD", "SITA"],
                  "transaction_type": "DFS PRIORITIES INCENTIVE", "report_base": [1, 2, 1], "actual_commission": [1200, 1800, 1200]}
                 ).to_csv(cm / "latest_commission.csv", index=False)
    monkeypatch.setattr(upload, "DFS_COUNTS", sup / "dfs.csv")
    monkeypatch.setattr(upload, "CM", cm)
    monkeypatch.setattr(upload, "load_metadata", lambda: {"commission": {"filename": "BC Report SEP-26.xlsx", "period_start": "2026-09-01", "period_end": "2026-09-30"}})
    rec = upload.dfs_incentive_reconciliation()
    assert rec["status"] == "READY", rec
    rows = {r["csp_id"]: r for r in rec["rows"]}
    assert rows["1A850001"]["csp_name"] == "Asha Devi" and rows["1A850001"]["bc_csp_name"] == "ASHA DEVI"
    assert rows["1A850002"]["csp_name"] == "RAM PRASAD" and rows["1A850002"]["status"] == "AMOUNT_MISMATCH"   # BC name fills a blank
    assert rows["1A850003"]["csp_name"] == "SITA" and rows["1A850003"]["status"] == "BC_ONLY_CSP"


def test_women_roster_before_bc_report_gives_a_clear_instruction(tmp_path, monkeypatch):
    from app.api import upload
    from app.main import app
    for name in ("WOMEN_COUNTS", "WOMEN_META", "CSP_IDENTITY", "CSP_IDENTITY_META"):
        monkeypatch.setattr(upload, name, tmp_path / (name.lower() + ".csv"))
    monkeypatch.setattr(upload, "CM", tmp_path / "no_bc")
    csv = ("CSP ID,CSP Name,Total Transaction Count Aug 2026\nOTHER ISSUE,Sample Agent,573\n").encode()
    r = TestClient(app).post("/api/upload/women-csp-roster", files={"file": ("Women_CSP_Aug.csv", BytesIO(csv), "text/csv")})
    assert r.status_code == 400
    assert "No BC Commission Report is uploaded yet" in r.json()["detail"] and "upload this Women CSP roster again" in r.json()["detail"]
    assert not (tmp_path / "women_counts.csv").exists()          # nothing saved from the rejected upload
