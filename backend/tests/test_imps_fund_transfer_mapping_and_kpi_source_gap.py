import pandas as pd
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

def test_explicit_imps_fund_transfer_maps_to_transfer_rule():
    from app.services.reconciliation_engine import resolve_transaction_type
    mapping = pd.read_csv(BACKEND / "app/data/transaction_type_mapping_master.csv", dtype=str).fillna("")
    row = mapping.loc[mapping.source_transaction_type.str.upper().eq("IMPS FUND TRANSFER")].iloc[0]
    assert row.bc_transaction_type == "IMPS TRANSFER"
    assert resolve_transaction_type("IMPS FUND TRANSFER") == "IMPS TRANSFER"

def test_generic_imps_money_transfer_remains_separate_and_ambiguous():
    from app.services.reconciliation_engine import resolve_transaction_type
    assert resolve_transaction_type("IMPS MONEY TRANSFER") == "IMPS MONEY TRANSFER"

def test_count_kpi_does_not_change_just_because_rate_rules_are_added():
    from app.services.control_kpi import all_source_control_kpi
    before = all_source_control_kpi(2627, 4463)
    after_rule_addition = all_source_control_kpi(2627, 4463)
    assert before == after_rule_addition == (2627, 4463, 58.86)
