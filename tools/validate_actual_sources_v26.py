import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.rate_master import build_rate_master_from_workbook
from app.services.reconciliation_engine import reconcile_transactions
from app.services.transaction_processor import get_successful_transactions

if len(sys.argv) != 4:
    raise SystemExit("Usage: python tools/validate_actual_sources_v26.py <success.xlsx> <bc.xlsx> <sbi_master.xlsx>")
success=pd.read_excel(sys.argv[1]); bc=pd.read_excel(sys.argv[2], sheet_name="CSP Wise Transaction Type Wise"); master=Path(sys.argv[3])
rules,_=build_rate_master_from_workbook(master.read_bytes(),master.name)
tx=success.rename(columns={"CSP Code New":"csp_id","Reference Number":"transaction_id","Type of Transaction":"transaction_type","Amount":"amount","Status":"status","New Date":"transaction_date"})
cm=bc.rename(columns={"CSP Code":"csp_id","Transaction Type":"transaction_type","Commission":"actual_commission","Num Txns / Avg Bal":"report_base"})
tx=get_successful_transactions(tx)
r=reconcile_transactions(tx,cm,rules)
# Supplemental incentive/control rows can reference core transactions; keep them
# out of source transaction counts and count-match denominator.
core=r[~r.get("is_supplemental",pd.Series(False,index=r.index)).fillna(False).astype(bool)].copy()
supp=r[r.get("is_supplemental",pd.Series(False,index=r.index)).fillna(False).astype(bool)].copy()
sc=(core.successful_transactions>0) & core.report_base.notna()
match=(sc & core.count_variance.fillna(1).eq(0))
print("Core successful source transactions:",int(core.successful_transactions.sum()))
print("Core CSP+type groups with count control:",int(sc.sum()))
print("Exact count-match groups:",int(match.sum()))
print("Source count match rate:",round(match.sum()/sc.sum()*100,2) if sc.any() else 0)
print("Core deterministic expected:",round(float(pd.to_numeric(core.expected_commission,errors="coerce").sum()),2))
print("Core expected scenario low:",round(float(pd.to_numeric(core.expected_commission_low,errors="coerce").sum()),2))
print("Core expected scenario high:",round(float(pd.to_numeric(core.expected_commission_high,errors="coerce").sum()),2))
print("Core settlement-approved expected:",round(float(pd.to_numeric(core.loc[core.settlement_rule_approved.fillna(False),"expected_commission"],errors="coerce").sum()),2))
print("Core settlement-approved actual:",round(float(pd.to_numeric(core.loc[core.settlement_rule_approved.fillna(False),"actual_comparable_commission"],errors="coerce").sum()),2))
print("Successful core rows requiring geography scenario:",int(pd.to_numeric(core.get("geography_unresolved_transactions"),errors="coerce").fillna(0).sum()))
print("Successful core rows with unresolved rule/type:",int(core.loc[core.reconciliation_status.isin(["Rate Master Missing","Unmapped Transaction Type"]),"successful_transactions"].sum()))
print("Count-mismatch successful core rows:",int(core.loc[core.reconciliation_status.eq("Count Mismatch"),"successful_transactions"].sum()))
print("Supplemental control rows (not additional source transactions):",len(supp))
print("Supplemental expected commission:",round(float(pd.to_numeric(supp.expected_commission,errors="coerce").sum()),2))
