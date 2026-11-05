from pathlib import Path
import pandas as pd
from app.services.rate_master import calculate_expected

ROOT = Path(__file__).resolve().parents[1] / "app" / "data" / "rate_master"

def _rules():
    return pd.read_csv(ROOT / "latest_rate_master.csv", low_memory=False)

def test_screenshot_supported_remittance_home_and_non_home_slabs_are_confirmed():
    rules = _rules()
    subset = rules[rules["rule_id"].astype(str).str.match(r"^CM0(18|21)-")]
    assert len(subset) == 16
    assert set(subset["rule_status"].astype(str).str.upper()) == {"CONFIRMED"}
    assert subset["source"].astype(str).str.contains("user-supplied SBI schedule screenshot", case=False).all()

def _calc(label, amount, channel):
    tx = pd.DataFrame([{"rule_type": label, "csp_id": "CSP001", "amount": amount,
                        "channel": channel, "transaction_date": "2026-10-15", "kyc_type": ""}])
    out, _ = calculate_expected(tx, _rules())
    return out.iloc[0]

def test_home_transfer_slabs_use_separate_rural_and_urban_rates():
    assert _calc("FUNDTRANSFER - HOME", 5000, "RURAL").expected_commission == 10.00
    assert _calc("FUNDTRANSFER - HOME", 5000, "URBAN").expected_commission == 12.00
    assert _calc("FUNDTRANSFER - HOME", 12000, "RURAL").expected_commission == 12.00
    assert _calc("FUNDTRANSFER - HOME", 12000, "URBAN").expected_commission == 15.00

def test_non_home_cash_remittance_slabs_use_separate_rural_and_urban_rates():
    assert _calc("FUNDTRANSFER - NON HOME", 5000, "RURAL").expected_commission == 8.00
    assert _calc("FUNDTRANSFER - NON HOME", 5000, "URBAN").expected_commission == 10.00
    assert _calc("FUNDTRANSFER - NON HOME", 12000, "RURAL").expected_commission == 10.00
    assert _calc("FUNDTRANSFER - NON HOME", 12000, "URBAN").expected_commission == 12.00


def test_startup_reset_rebuild_preserves_confirmed_remittance_overrides():
    from app.services.rate_master import build_rate_master_from_workbook, apply_confirmed_remittance_reference_rules
    workbook = ROOT.parent / "expected_commission_rule" / "latest.xlsx"
    parsed, validation = build_rate_master_from_workbook(workbook.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    assert validation["valid"] is True
    overlaid = apply_confirmed_remittance_reference_rules(parsed)
    rows = overlaid[overlaid["rule_id"].astype(str).str.match(r"^CM0(18|21)-")]
    assert len(rows) == 16
    assert set(rows["rule_status"].astype(str).str.upper()) == {"CONFIRMED"}
