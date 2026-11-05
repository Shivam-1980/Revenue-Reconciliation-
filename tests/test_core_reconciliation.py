"""Deterministic regression test for the financial reconciliation engine.
Run with: python tests/test_core_reconciliation.py
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.rate_master import validate_rate_master
from app.services.reconciliation_engine import reconcile_transactions
from app.services.time_reconciliation import time_reconciliation


def test_core_reconciliation_regression():
    # Inline approved master: parent product + amount slabs + month-specific rule.
    master = pd.DataFrame([
        ["Account Oppening (PMJDY)", "Initial deposit < Rs. 100", 20, "Commission", "Monthly"],
        [None, "Initial deposit >= Rs. 100 to < Rs. 500", 30, "Commission", "Monthly"],
        [None, "Initial deposit >= Rs. 500 to < Rs. 1000", 40, "Commission", "Monthly"],
        [None, "Initial deposit >= Rs. 1000", 50, "Commission", "Monthly"],
        ["PMJJBY", "Q1 (June-July-August)", 30, "Commission", "Monthly"],
        ["PMJJBY", "Q2 (Sep-Oct-Nov)", 23, "Commission", "Monthly"],
        ["MONEY TRANSFER", None, 9, "Transactional", "Monthly"],
    ], columns=["Component", "Sub Category/Rule", "Avg. per enrollment revenue", "Enrollment Type", "Commission Cycle"])
    rules, info = validate_rate_master(master)
    assert info["valid"]

    tx = pd.DataFrame([
        ["R1", "C1", "Initial deposit", 50, "SUCCESS", "2026-08-01"],
        ["R2", "C1", "Initial deposit", 100, "SUCCESS", "2026-08-01"],
        ["R3", "C1", "Initial deposit", 500, "SUCCESS", "2026-08-01"],
        ["R4", "C1", "Initial deposit", 1000, "SUCCESS", "2026-08-01"],
        ["R5", "C1", "PMJJBY", 0, "SUCCESS", "2026-08-01"],
        ["R6", "C1", "Money Transfer", 1000, "SUCCESS", "2026-08-01"],
    ], columns=["transaction_id", "csp_id", "transaction_type", "amount", "status", "transaction_date"])
    cm = pd.DataFrame([
        ["C1", "ACC OPEN WITH EKYC AND INIT DEP BELOW 100", 1, 20],
        ["C1", "ACC OPEN WITH EKYC AND INIT DEP BTWN 100 AND 499", 1, 30],
        ["C1", "ACC OPEN WITH EKYC AND INIT DEP BTWN 500 AND 999", 1, 40],
        ["C1", "ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE", 1, 50],
        ["C1", "PMJJBY", 1, 30],
        ["C1", "MONEY TRANSFER", 1, 9],
    ], columns=["csp_id", "transaction_type", "report_base", "actual_commission"])

    r = reconcile_transactions(tx, cm, rules)
    assert int(r.successful_transactions.sum()) == 6
    assert abs(float(pd.to_numeric(r.expected_commission, errors="coerce").sum()) - 170) < 0.005
    assert abs(float(pd.to_numeric(r.actual_comparable_commission, errors="coerce").sum()) - 170) < 0.005
    assert abs(float(pd.to_numeric(r.financial_gap, errors="coerce").sum())) < 0.005
    assert int((r.reconciliation_status == "MATCH").sum()) == 5
    money = r[r.transaction_type.eq('MONEY TRANSFER')].iloc[0]
    assert money.reconciliation_status == 'RATE_MASTER_MISSING'
    assert pd.isna(money.expected_commission)  # never substitute an unrelated slab rate

    # The period engine must not crash and must keep date semantics deterministic.
    daily = time_reconciliation(tx, cm, rules, grain="day", commission_date_granularity="date")
    assert "period" in daily.columns


def test_source_alignment_separates_measurement_types_and_unmapped():
    import pandas as pd
    from app.services.reconciliation_engine import reconcile_transactions
    tx = pd.DataFrame([
        {'csp_id':'C1','transaction_type':'Money Transfer','amount':1000,'transaction_date':'2026-08-01'},
        {'csp_id':'C1','transaction_type':'PPF SSA TXN','amount':100,'transaction_date':'2026-08-01'},
    ])
    cm = pd.DataFrame([
        {'csp_id':'C1','transaction_type':'MONEY TRANSFER','report_base':0,'actual_commission':0},
        {'csp_id':'C1','transaction_type':'AVERAGE BALANCE MAINTENANCE','report_base':5000,'actual_commission':10},
    ])
    r = reconcile_transactions(tx, cm, None)
    mt = r.loc[r['transaction_type'].eq('MONEY TRANSFER')].iloc[0]
    assert mt['measurement_type'] == 'TRANSACTION_COUNT'
    assert mt['reconciliation_status'] == 'SOURCE_COUNT_DIFFERENCE'
    assert mt['count_variance'] == 1
    ppf = r.loc[r['transaction_type'].eq('PPF SSA TXN')].iloc[0]
    assert ppf['reconciliation_status'] == 'UNMAPPED'
    bal = r.loc[r['measurement_type'].eq('AVERAGE_BALANCE')].iloc[0]
    assert pd.isna(bal['count_variance'])


def test_full_bc_transaction_source_aggregation_includes_bc_only_activity():
    from app.services.reconciliation_engine import reconcile_transactions, aggregate_by_transaction_type
    tx = pd.DataFrame([
        {'csp_id':'C1','transaction_type':'Customer enroll for SSS','amount':20,'transaction_date':'2026-08-01'},
        {'csp_id':'C2','transaction_type':'Initial deposit','amount':100,'transaction_date':'2026-08-01'},
    ])
    cm = pd.DataFrame([
        {'csp_id':'C1','transaction_type':'PMSBY','report_base':2,'actual_commission':2},
        {'csp_id':'C3','transaction_type':'PMSBY','report_base':5,'actual_commission':5},
        {'csp_id':'C2','transaction_type':'ACC OPEN WITH EKYC AND INIT DEP BTWN 100 AND 499','report_base':3,'actual_commission':90},
        {'csp_id':'C4','transaction_type':'ACC OPEN WITH EKYC AND INIT DEP BELOW 100','report_base':4,'actual_commission':80},
    ])
    r = reconcile_transactions(tx, cm, None)
    a = aggregate_by_transaction_type(r)
    sss = a.loc[a.transaction_type.eq('CUSTOMER ENROLL FOR SSS')].iloc[0]
    # Customer enroll for SSS is a successful-source product classification only;
    # the mapping workbook says there is no equivalent BC transaction type, so
    # PMJJBY/PMSBY rows must remain BC-only activity and never be compared.
    assert pd.isna(sss.bc_report_base_total)
    assert pd.isna(sss.bc_report_base_overlap)
    assert pd.isna(sss.bc_only_base)
    dep = a.loc[a.transaction_type.eq('INITIAL DEPOSIT')].iloc[0]
    assert float(dep.bc_report_base_total) == 7
    assert float(dep.bc_only_base) == 4


def test_successful_statuses_and_missing_dates_are_consistent_across_validation_and_processing():
    from app.services.file_processor import normalize_columns
    from app.services.validator import validate_transaction_data
    from app.services.transaction_processor import get_successful_transactions
    df = pd.DataFrame({
        'Reference Number':['A','B','C'],
        'CSP Code':['C1','C1','C1'],
        'Transaction Type':['MONEY TRANSFER']*3,
        'Amount':[100,200,300],
        'Transaction Date':['2026-08-01',None,'2026-08-03'],
        'Status':['SUCCESS TRANSACTION','SUCCESSFUL TRANSACTION','COMPLETED']
    })
    std, validation = validate_transaction_data(normalize_columns(df))
    processed = get_successful_transactions(std)
    assert validation['processable_rows'] == 2
    assert processed['transaction_id'].tolist() == ['A','C']


def test_explicit_unmapped_master_status_cannot_be_bypassed_by_exact_reference_vocab():
    from app.services.reconciliation_engine import resolve_transaction_type
    # The current controlled master explicitly marks PPF SSA TXN as UNMAPPED.
    # Even if a future uploaded rate/report file repeats that label, this is not
    # an approved transaction-type mapping and must remain an exception.
    assert resolve_transaction_type("PPF SSA TXN", 100, {"PPFSSATXN": "PPF SSA TXN"}) is None
    assert resolve_transaction_type("AEPS OFFUS Fund Transfer", 100, {"AEPSOFFUSFUNDTRANSFER": "AEPS OFFUS FUND TRANSFER"}) is None


def test_successful_transaction_processor_excludes_nonblank_but_invalid_dates():
    from app.services.transaction_processor import get_successful_transactions
    df = pd.DataFrame({
        'transaction_id': ['VALID', 'BAD_DATE'],
        'csp_id': ['C1', 'C1'],
        'transaction_type': ['MONEY TRANSFER', 'MONEY TRANSFER'],
        'amount': [100, 200],
        'transaction_date': ['2026-08-01', '31/19/2026'],
        'status': ['SUCCESS', 'SUCCESS'],
    })
    processed = get_successful_transactions(df)
    assert processed['transaction_id'].tolist() == ['VALID']


def test_successful_transaction_processor_requires_normalized_financial_fields():
    from app.services.transaction_processor import get_successful_transactions
    try:
        get_successful_transactions(pd.DataFrame({'transaction_id': ['A']}))
    except ValueError as exc:
        assert 'missing required normalized columns' in str(exc)
    else:
        raise AssertionError('Missing mandatory transaction columns must not silently pass.')
