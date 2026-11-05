"""SBI monthly expected-commission evidence engine.

Separates transaction-level expected commission from monthly CSP incentives/reimbursements.
It never substitutes actual commission amounts for expected values.
"""
from __future__ import annotations
import pandas as pd
from .number_parser import parse_numeric_series


def _norm(s):
    return " ".join(str(s or "").strip().upper().split())


def calculate_monthly_components(commission: pd.DataFrame, dfs_reconciliation: dict | None = None, reconciled_rows: pd.DataFrame | None = None, matm_source: pd.DataFrame | None = None) -> dict:
    """Calculate monthly components that are directly supported by BC report bases.

    The BC report's `Num Txns / Avg Bal` is treated as an input quantity only for
    rules whose SBI formula is directly expressed on that quantity. Actual
    commission is never used as the calculation base.
    """
    cm = commission.copy()
    if cm.empty:
        return {"verified_earnings": 0.0, "conditional_earnings": 0.0,
                "components": [], "required_evidence": []}
    cm["transaction_type_norm"] = cm["transaction_type"].map(_norm)
    # SBI rule description alias for CM060. The bank report may use the
    # operational label while the rule master uses the descriptive wording.
    cm["transaction_type_norm"] = cm["transaction_type_norm"].replace({
        "INCENTIVE ON CASH TRANSACTIONS DONE THROUGH M-ATMS": "MATM CASH TRANSACTIONS INCENTIVE",
        "INCENTIVE ON CASH TRANSACTIONS DONE THROUGH M ATMS": "MATM CASH TRANSACTIONS INCENTIVE",
        "M-ATM CASH TRANSACTION INCENTIVE": "MATM CASH TRANSACTIONS INCENTIVE",
        "M ATM CASH TRANSACTION INCENTIVE": "MATM CASH TRANSACTIONS INCENTIVE",
    })
    cm["csp_id_norm"] = cm["csp_id"].map(_norm)
    cm["base"] = parse_numeric_series(cm.get("report_base", pd.Series(pd.NA, index=cm.index)))

    components=[]
    verified=0.0
    conditional=0.0

    def add(name, amount, status, formula, evidence, source_rows=0, notes=""):
        nonlocal verified, conditional
        amount = round(float(amount),2) if amount is not None else None
        components.append({"component":name,"amount":amount,"status":status,
                           "formula":formula,"evidence":evidence,"source_rows":int(source_rows),"notes":notes})
        if amount is not None:
            if status == "VERIFIED": verified += amount
            else: conditional += amount

    # CM058 expected revenue comes from successful AEPS cash-withdrawal source
    # rows × ₹1. Never derive expected revenue from the BC report's own base or
    # paid amount; those are the independent actual-side evidence.
    cm058_label = "ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS"
    if reconciled_rows is not None and not reconciled_rows.empty and "transaction_type" in reconciled_rows.columns:
        source_cm058 = reconciled_rows[reconciled_rows["transaction_type"].map(_norm).eq(cm058_label)].copy()
        if not source_cm058.empty:
            expected = pd.to_numeric(source_cm058.get("expected_commission"), errors="coerce")
            approved = source_cm058.get("settlement_rule_approved", pd.Series(True, index=source_cm058.index)).astype("boolean").fillna(False)
            complete = bool(expected.notna().all()) and bool(approved.all())
            add("Additional incentive on AEPS cash transactions", expected.sum(min_count=1), "VERIFIED" if complete else "CONDITIONAL",
                "eligible successful AEPS cash-withdrawal count × ₹1", "Successful transaction source + SBI CM058", int(pd.to_numeric(source_cm058.get("successful_transactions"), errors="coerce").sum()),
                "Only AEPS withdrawal subtypes currently included; deposits/fund transfers are not inferred eligible from the supplied rule screenshot.")
    elif cm.transaction_type_norm.eq(cm058_label).any():
        components.append({"component":"Additional incentive on AEPS cash transactions","amount":None,"status":"EVIDENCE REQUIRED",
                           "formula":"Eligible successful AEPS cash-withdrawal count × ₹1",
                           "evidence":"Successful transaction source and approved CM058 eligible-type mapping",
                           "source_rows":int(cm.transaction_type_norm.eq(cm058_label).sum()),
                           "notes":"BC report base/actual amount is not used to infer expected revenue."})

    # CM060: independent CSP-wise monthly m-ATM count source × ₹3, capped at ₹1,000/CSP/month.
    # Never calculate expected commission from the BC report's own quantity: BC rows are actual-side evidence.
    d=cm[cm.transaction_type_norm.eq("MATM CASH TRANSACTIONS INCENTIVE")].copy()
    if matm_source is not None and not matm_source.empty:
        src=matm_source.copy()
        if {"csp_id","matm_transaction_count"}.issubset(src.columns):
            src["csp_id_norm"]=src["csp_id"].map(_norm)
            src["matm_transaction_count"]=pd.to_numeric(src["matm_transaction_count"],errors="coerce")
            src=src[src["csp_id_norm"].ne("") & src["matm_transaction_count"].notna() & (src["matm_transaction_count"]>=0)]
            group_keys=(["period","csp_id_norm"] if "period" in src.columns else ["csp_id_norm"])
            src_by_period=src.groupby(group_keys)["matm_transaction_count"].sum()
            expected_by_period=(src_by_period*3).clip(upper=1000)
            expected_total=float(expected_by_period.sum())
            src_by=src.groupby("csp_id_norm")["matm_transaction_count"].sum()
            expected_by=expected_by_period.groupby(level="csp_id_norm").sum() if isinstance(expected_by_period.index,pd.MultiIndex) else expected_by_period
            if not d.empty:
                d["actual_commission_numeric"]=pd.to_numeric(d.get("actual_commission",pd.Series(0.0,index=d.index)),errors="coerce").fillna(0.0)
                actual_by=d.dropna(subset=["base"]).groupby("csp_id_norm").agg(
                    actual_count=("base","sum"),
                    actual_amount=("actual_commission_numeric","sum")
                )
                # If actual_commission was absent, do not pretend base is an amount.
                if "actual_commission" not in d.columns:
                    actual_by["actual_amount"]=0.0
            else:
                actual_by=pd.DataFrame(columns=["actual_count","actual_amount"])
            matched=set(src_by.index)&set(actual_by.index)
            actual_total=float(pd.to_numeric(actual_by.get("actual_amount",pd.Series(dtype=float)),errors="coerce").fillna(0).sum())
            matched_expected=float(expected_by.reindex(list(matched)).fillna(0).sum())
            matched_actual=float(actual_by.reindex(list(matched)).get("actual_amount",pd.Series(dtype=float)).fillna(0).sum())
            variance=round(actual_total-expected_total,2)
            item={"component":"m-ATM cash transaction incentive","amount":round(expected_total,2),"status":"VERIFIED",
                  "formula":"sum over CSPs: min(uploaded monthly eligible m-ATM count × ₹3, ₹1,000)",
                  "evidence":"Independent current-period CSP m-ATM source + SBI CM060; BC Report used only for actual paid amount",
                  "source_rows":int(len(src)),"notes":f"Source transactions={int(src['matm_transaction_count'].sum())}; CSP IDs present in both source and BC={len(matched)}; source-only CSPs={len(set(src_by.index)-set(actual_by.index))}; BC-only CSPs={len(set(actual_by.index)-set(src_by.index))}. Some source-only rows have zero expected; inspect per-CSP statuses. Expected and actual remain separate.",
                  "actual_amount":round(actual_total,2),"variance_actual_minus_expected":variance,
                  "actual_reported_count":round(float(actual_by.get("actual_count",pd.Series(dtype=float)).sum()),2),
                  "source_transaction_count":int(src["matm_transaction_count"].sum()),"source_csp_controls":int(src_by.size),
                  "matched_csp_controls":int(len(matched)),"matched_expected_amount":round(matched_expected,2),
                  "matched_actual_amount":round(matched_actual,2),"matched_variance":round(matched_actual-matched_expected,2)}
            components.append(item); verified+=expected_total
    elif not d.empty:
        # Fail closed if source is missing. A BC-reported base must not become its own expected base.
        components.append({"component":"m-ATM cash transaction incentive","amount":None,"status":"EVIDENCE REQUIRED",
            "formula":"min(uploaded CSP monthly count × ₹3, ₹1,000)","evidence":"Current-period CSP m-ATM source missing",
            "source_rows":int(len(d)),"actual_amount":round(float(pd.to_numeric(d.get("actual_commission",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),2),
            "notes":"BC report values are actual-side only; upload current-period CSP-wise m-ATM counts to calculate expected commission."})

    # CM061: ₹5 per TAB financial transaction, capped at ₹1,000 per CSP/month.
    d=cm[cm.transaction_type_norm.isin(["TAB TRANSACTIONS INCENTIVE","TAB FINANCIAL TRANSACTIONS INCENTIVE"])]
    if not d.empty and d.base.notna().any():
        by=d.dropna(subset=["base"]).groupby("csp_id_norm")["base"].sum()
        add("TAB transaction incentive", (by*5).clip(upper=1000).sum(), "VERIFIED",
            "min(CSP monthly qualifying count × ₹5, ₹1,000)", "BC report CSP-level base + SBI CM061", len(d))

    # CM074: Monthly Passbook Printer Cost Reimbursement.
    # Approved rule provided by the user: if a passbook printer is active,
    # reimbursement is ₹610 monthly. In the BC CSP-wise transaction-type
    # control, the reported quantity is the count of paid printer-month units.
    # Calculate this control from that count (never from Passbook Printing
    # volume or the full printer roster count), and keep it separate from
    # per-print Passbook Printing commission.
    d=cm[cm.transaction_type_norm.eq("PASSBOOK PRINTER COST REIMBURSEMENT")]
    if not d.empty:
        paid_count = int(pd.to_numeric(d["base"], errors="coerce").fillna(0).sum())
        actual_col = "actual_commission" if "actual_commission" in d.columns else ("commission" if "commission" in d.columns else None)
        paid_amount = round(float(pd.to_numeric(d[actual_col], errors="coerce").fillna(0).sum()), 2) if actual_col else None
        expected_amount = round(paid_count * 610.0, 2)
        amount_matches = paid_amount is not None and abs(paid_amount - expected_amount) < 0.005
        add("Passbook printer cost reimbursement", expected_amount,
            "VERIFIED" if amount_matches else "CONDITIONAL",
            "BC report printer-month quantity × ₹610 (monthly active-printer rule)",
            "Current-period BC Report CSP Wise Transaction Type Wise quantity + SBI CM074 rate",
            int(len(d)),
            "Separate from Passbook Printing per-print commission. This is the user's approved count-based monthly control; if expected and actual differ, inspect the CSP-level rows rather than using the full printer roster count.")
        # Expose paid-side values for transparent UI/audit comparison.
        components[-1]["actual_amount"] = paid_amount
        components[-1]["actual_paid_printer_months"] = paid_count
        components[-1]["variance"] = round((paid_amount or 0.0) - expected_amount, 2) if paid_amount is not None else None

    # DFS is a monthly incentive. Its expected amount must come from the
    # uploaded CSP-wise assigned-slab source and the user-approved permanent
    # DFS rule master—not from the BC report's base or paid amount. Using the
    # bank's own slab/base to derive expectation would make the reconciliation
    # circular and could conceal missing/incorrect payments.
    dfs_rows = (dfs_reconciliation or {}).get("rows") or []
    dfs_summary = (dfs_reconciliation or {}).get("summary") or {}
    if (dfs_reconciliation or {}).get("available") and (dfs_reconciliation or {}).get("status") == "READY":
        dfs_expected = dfs_summary.get("expected_total")
        unresolved = int(dfs_summary.get("unresolved_source_rows") or 0)
        if dfs_expected is not None:
            dfs_status = "VERIFIED" if unresolved == 0 else "CONDITIONAL"
            add("DFS Priorities Incentive", dfs_expected, dfs_status,
                "Sum of monthly CSP-assigned slabs × permanent approved DFS rates",
                "Uploaded monthly DFS CSP/slab sheet + DFS rule master", int(dfs_summary.get("source_rows") or len(dfs_rows)),
                "" if unresolved == 0 else f"{unresolved} source CSP row(s) remain unresolved; amount is displayed but excluded from verified monthly earnings.")
    elif cm.transaction_type_norm.eq("DFS PRIORITIES INCENTIVE").any():
        components.append({"component":"DFS Priorities Incentive","amount":None,"status":"EVIDENCE REQUIRED",
                           "formula":"Monthly CSP-assigned slab × approved fixed monthly rate",
                           "evidence":"Upload and period-match the DFS CSP/slab sheet",
                           "source_rows":int(cm.transaction_type_norm.eq("DFS PRIORITIES INCENTIVE").sum()),
                           "notes":"The BC report amount/base is not used to infer the expected DFS amount."})

    # These categories need evidence that is not present in the current BC report
    # base, so they are explicitly surfaced rather than inferred from actual payout.
    evidence_rules=[
        ("RURAL COMMISSION","login days + qualifying PMJDY/transaction evidence"),
        ("AVERAGE BALANCE MAINTENANCE","weekly average balance + minimum 200 BSBD accounts"),
        ("WOMEN CSP INCENTIVE","approved women-CSP status + transaction-based expected commission"),
        ("5 STAR INCENTIVE","A-rating, passbook printer, m-ATM, UV lamp and voice-prompt qualification"),
    ]
    for typ,ev in evidence_rules:
        if cm.transaction_type_norm.eq(typ).any():
            components.append({"component":typ.title(),"amount":None,"status":"EVIDENCE REQUIRED",
                               "formula":"SBI rule requires additional CSP-level evidence","evidence":ev,
                               "source_rows":int(cm.transaction_type_norm.eq(typ).sum()),"notes":"No amount inferred from BC actual commission."})

    return {"verified_earnings":round(verified,2),"conditional_earnings":round(conditional,2),
            "components":components,"required_evidence":[c for c in components if c["status"]=="EVIDENCE REQUIRED"]}
