from pathlib import Path
import pandas as pd
from app.services.rate_master import build_rate_master_from_workbook

RULE_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "expected_commission_rule" / "latest.xlsx"


def test_consolidated_sbi_rule_master_is_parsed_without_guessing():
    normalized, validation = build_rate_master_from_workbook(RULE_PATH.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    assert validation["valid"] is True
    assert validation["rows"] == 71
    assert validation["rules"] >= 80
    assert not normalized.empty
    assert {"transaction_type", "rate", "rate_type", "rule_id", "commercial_scope", "rule_status"}.issubset(normalized.columns)


def test_percentage_cash_withdrawal_has_geography_floor_and_cap():
    normalized, _ = build_rate_master_from_workbook(RULE_PATH.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    rules = normalized[normalized["transaction_type"].eq("CASH WITHDRAWAL") & normalized["rate_type"].eq("PERCENTAGE")]
    assert len(rules) == 2
    assert set(pd.to_numeric(rules["rate"]).tolist()) == {0.5}
    assert set(pd.to_numeric(rules["floor"]).tolist()) == {3.0}
    assert set(pd.to_numeric(rules["cap"]).tolist()) == {15.0, 17.0}
    assert set(rules["channel"].tolist()) == {"RURAL", "URBAN"}


def test_fee_share_imps_rule_uses_customer_fee_basis_not_transaction_amount():
    normalized, _ = build_rate_master_from_workbook(RULE_PATH.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    cash = normalized[normalized["transaction_type"].eq("IMPS CASH")]
    transfer = normalized[normalized["transaction_type"].eq("IMPS TRANSFER")]
    assert len(cash) == 1 and len(transfer) == 1
    assert set(cash["rate_type"].tolist()) == {"FEE_PERCENTAGE"}
    assert set(transfer["rate_type"].tolist()) == {"FEE_PERCENTAGE"}
    assert float(cash.iloc[0]["rate"]) == 80.0
    assert float(transfer.iloc[0]["rate"]) == 50.0
    assert cash.iloc[0]["basis"].startswith("fee_rate=0.7")
    assert transfer.iloc[0]["basis"].startswith("fee_rate=0.7")


def test_account_level_caps_and_ambiguous_apy_range_are_not_executable():
    normalized, validation = build_rate_master_from_workbook(RULE_PATH.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    assert not normalized["transaction_type"].eq("PASSBOOK PRINTING").any()
    assert not normalized["transaction_type"].str.contains("MINI STATEMENT", case=False).any()
    assert not normalized["transaction_type"].str.startswith("APY").any()
    assert any("APY" in warning and "range" in warning for warning in validation["warnings"])


def test_consolidated_master_keeps_product_specific_rules_missing_from_generic_sheet():
    normalized, validation = build_rate_master_from_workbook(RULE_PATH.read_bytes(), "SBI_Expected_Commission_Rule.xlsx")
    # Product-specific BC rules remain available for transaction labels not represented
    # in the consolidated generic service table.
    assert normalized["transaction_type"].eq("AEPS ONUS WITHDRAWAL").any()
    assert normalized["transaction_type"].eq("MATM ONUS DEPOSIT").any()
    # The new source explicitly requires account-level caps; these must not be
    # bypassed by a legacy per-transaction rule.
    assert not normalized["transaction_type"].eq("PASSBOOK PRINTING").any()
    assert not normalized["transaction_type"].eq("MATM MINI STATEMENT").any()
