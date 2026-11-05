"""Run a source-level validation against three uploaded files.

Usage:
  python tools/validate_actual_sources.py <success.xlsx> <bc_report.xlsx> <sbi_master.xlsx>
"""
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.rate_master import build_rate_master_from_workbook
from app.services.reconciliation_engine import reconcile_transactions
from app.services.transaction_processor import get_successful_transactions

if len(sys.argv) != 4:
    raise SystemExit(__doc__)
# Successful transactions are stored on the explicitly named Success worksheet
# in the uploaded monthly workbook; never default to the first sheet (often GTV).
try:
    success = pd.read_excel(sys.argv[1], sheet_name="Success")
except ValueError:
    success = pd.read_excel(sys.argv[1])
bc = pd.read_excel(sys.argv[2], sheet_name="CSP Wise Transaction Type Wise")
master = Path(sys.argv[3])
rules, meta = build_rate_master_from_workbook(master.read_bytes(), master.name)
tx = success.rename(columns={'CSP Code New':'csp_id','Reference Number':'transaction_id','Type of Transaction':'transaction_type','Amount':'amount','Status':'status','New Date':'transaction_date'})
cm = bc.rename(columns={'CSP Code':'csp_id','Transaction Type':'transaction_type','Commission':'actual_commission','Num Txns / Avg Bal':'report_base'})
tx = get_successful_transactions(tx)
r = reconcile_transactions(tx, cm, rules)
# The engine also emits supplemental control rows (e.g. CM058 incentive) that
# intentionally reference eligible core transactions. Do not count those rows
# as additional successful source transactions or transaction-type groups.
is_supplemental = r.get('is_supplemental', pd.Series(False, index=r.index, dtype='boolean')).astype('boolean').fillna(False).astype(bool)
core = r[~is_supplemental].copy()
supp = r[is_supplemental].copy()
count_control=(core.successful_transactions>0)&core.report_base.notna()
count_match=(count_control & pd.to_numeric(core.count_variance, errors='coerce').fillna(1).eq(0)).sum()
print('Core successful source transactions:', int(core.successful_transactions.sum()))
print('Core CSP/type groups with count control:', int(count_control.sum()))
print('Exact count-match groups:', int(count_match))
print('Count match rate:', round(float(count_match/count_control.sum()*100),2) if count_control.any() else 0)
print('Core calculated expected commission:', round(float(pd.to_numeric(core.expected_commission,errors='coerce').sum()),2))
approved=(core.successful_transactions>0)&core.settlement_rule_approved.astype('boolean').fillna(False).astype(bool)
print('Core settlement-approved expected:', round(float(pd.to_numeric(core.loc[approved,'expected_commission'],errors='coerce').sum()),2))
print('Core settlement-approved actual:', round(float(pd.to_numeric(core.loc[approved,'actual_comparable_commission'],errors='coerce').sum()),2))
print('Unresolved core source transactions:', int(core.loc[(core.successful_transactions>0)&core.join_type.isna(),'successful_transactions'].sum()))
print('Supplemental control rows (not additional source transactions):', len(supp))
print('Supplemental expected commission:', round(float(pd.to_numeric(supp.expected_commission,errors='coerce').sum()),2))
