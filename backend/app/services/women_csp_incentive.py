"""SBI Rule 24: month-agnostic Women CSP incentive reconciliation.

Expected incentive = min(10% of eligible transaction-based commission, ₹1,000 per CSP/month).
The expected base is built from transaction/service commission rows in the BC report,
excluding separate incentives, non-transaction monthly components, reimbursements and penalties.
Actual payout is sourced only from the explicit WOMEN CSP INCENTIVE row.
"""
from __future__ import annotations
import re
import pandas as pd

RULE_NAME = "Transactions done at Women CSP outlets"
INCENTIVE_TYPE = "WOMEN CSP INCENTIVE"
RATE = 0.10
MONTHLY_CAP = 1000.0

# Explicit SBI transaction/service commission allowlist. It is configuration, not
# monthly activity data. Unknown/new BC rows are excluded pending rule/mapping review,
# rather than silently being treated as transaction-based commission.
ELIGIBLE_BASE_TYPES = {
    "AEPS ONUS WITHDRAWAL", "MONEY TRANSFER", "AEPS MINI STATEMENT - ONUS",
    "ACCOUNT REKYC", "PMJJBY", "AEPS ACQUIRER WITHDRAWAL", "CASH WITHDRAWAL",
    "PASSBOOK PRINTING", "DEBIT CARD ONUS", "AEPS ONUS DEPOSIT", "AADHAAR SEED",
    "ACC OPEN WITH EKYC AND INIT DEP BTWN 100 AND 499",
    "ACC OPEN WITH EKYC AND INIT DEP BELOW 100", "AEPS ONUS FUNDTRANSFER - HOME",
    "ACC OPEN WITH EKYC AND INIT DEP BTWN 500 AND 999",
    "EKYC CERTIFICATE GENERATION FOR CKYC", "LOAN DEPOSIT", "DEBIT CARD OFFUS",
    "ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE", "MATM ONUS FUNDSTRANSFER - HOME",
    "PMSBY", "MATM ONUS DEPOSIT", "IMPS FUNDTRANFER", "IMPS FUND TRANSFER", "IMPS FUNDTRANSFER", "IMPS TRANSFER", "CASH DEPOSIT",
    "MATM MINI STATEMENT", "GREEN PIN GENERATION", "RD OPEN", "FUNDTRANSFER - HOME",
    "STDR OPEN", "YONO CASH", "CHEQUE BOOK ISSUE REQUEST", "DEBIT CARD BLOCKING",
}

# Explicitly non-core lines. Keep this list conservative and auditable.
EXCLUDED_BASE_TYPES = {
    INCENTIVE_TYPE,
    "RURAL COMMISSION",
    "AVERAGE BALANCE MAINTENANCE",
    "DFS PRIORITIES INCENTIVE",
    "ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS",
    "MATM CASH TRANSACTIONS INCENTIVE",
    "TAB TRANSACTIONS INCENTIVE",
    "TAB FINANCIAL TRANSACTIONS INCENTIVE",
    "PASSBOOK PRINTER COST REIMBURSEMENT",
    "PENALTY FOR CSP INACTIVITY",
    "LAKSHYA DEPOSIT MOBILISATION CAMPAIGN INCENTIVE",
    "ADDITIONAL INCENTIVE - ASPIRATIONAL LWE DISTT",
    "5 STAR INCENTIVE",
    "AADHAAR SEEDING INCENTIVE",
    "GREEN PIN INCENTIVE",
    "RE-KYC INCENTIVE",
    "ACTIVATION OF INOPERATIVE PMJDY INCENTIVE",
    "P SEGMENT GOLD LOAN LEAD GENERATION",
    "PERSONAL LOAN LEAD GENERATION",
    "HOME LOAN LEAD GENERATION",
    "VEHICLE LOAN LEAD GENERATION",
    "MUDRA LOAN LEAD GENERATION",
}


def _norm(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().upper())


def _id(value):
    return re.sub(r"\.0$", "", _norm(value))


def reconcile_women_csp_incentive(roster: pd.DataFrame, bc: pd.DataFrame, period: str | None = None,
                                  id_aliases: dict[str, str] | None = None,
                                  expected_transactions: pd.DataFrame | None = None) -> dict:
    """Reconcile a current-period Women CSP roster against the current BC report.

    roster columns: csp_id, csp_name, transaction_count; optional period/status.
    bc columns: csp_id, csp_name, transaction_type, actual_commission; optional report_base.
    Does not infer eligibility from the actual incentive payout. A bank-paid CSP absent
    from the roster is reported separately as a master synchronization exception.
    """
    if roster is None or roster.empty:
        return {"available": False, "status": "WOMEN_ROSTER_MISSING", "message": "Upload the current-period Women CSP roster.", "rows": []}
    if bc is None or bc.empty:
        return {"available": False, "status": "BC_REPORT_MISSING", "message": "Upload the matching-period BC Commission Report.", "rows": []}
    required_roster = {"csp_id", "transaction_count"}
    required_bc = {"csp_id", "transaction_type", "actual_commission"}
    required_expected = {"csp_id", "expected_commission"}
    if expected_transactions is not None and not expected_transactions.empty and not required_expected.issubset(expected_transactions.columns):
        return {"available": False, "status": "EXPECTED_TRANSACTION_SCHEMA_INVALID", "message": f"Successful-transaction reconciliation requires {sorted(required_expected)}.", "rows": []}
    if not required_roster.issubset(roster.columns):
        return {"available": False, "status": "ROSTER_SCHEMA_INVALID", "message": f"Women CSP roster requires {sorted(required_roster)}.", "rows": []}
    if not required_bc.issubset(bc.columns):
        return {"available": False, "status": "BC_SCHEMA_INVALID", "message": f"BC report requires {sorted(required_bc)}.", "rows": []}

    r = roster.copy()
    b = bc.copy()
    for frame in (r, b):
        frame["csp_id"] = frame["csp_id"].map(_id)
    if "csp_name" not in r: r["csp_name"] = ""
    if "csp_name" not in b: b["csp_name"] = ""
    r["csp_name_norm"] = r["csp_name"].map(_norm)
    b["csp_name_norm"] = b["csp_name"].map(_norm)
    aliases = {_norm(k): _id(v) for k, v in (id_aliases or {}).items()}
    if aliases:
        mask = r["csp_id"].map(_norm).isin(aliases)
        r.loc[mask, "csp_id"] = r.loc[mask, "csp_id"].map(lambda x: aliases.get(_norm(x), _id(x)))
    # Reject duplicate roster IDs rather than double-counting incentive caps.
    valid_ids = r["csp_id"].str.fullmatch(r"1A85\d{4}", na=False)
    unresolved_roster = r[~valid_ids].copy()
    r = r[valid_ids].copy()
    if r["csp_id"].duplicated().any():
        duplicates = sorted(r.loc[r["csp_id"].duplicated(keep=False), "csp_id"].unique().tolist())
        return {"available": False, "status": "DUPLICATE_ROSTER_IDS", "message": f"Duplicate CSP IDs in Women CSP roster: {duplicates[:10]}. Resolve before reconciliation.", "rows": []}

    b["transaction_type_norm"] = b["transaction_type"].map(_norm)
    b["actual_commission"] = pd.to_numeric(b["actual_commission"], errors="coerce")
    if b["actual_commission"].isna().any():
        bad = int(b["actual_commission"].isna().sum())
        return {"available": False, "status": "BC_AMOUNT_INVALID", "message": f"{bad} BC commission rows have invalid/missing commission amounts.", "rows": []}
    b["transaction_count"] = pd.to_numeric(b.get("report_base", pd.Series(0, index=b.index)), errors="coerce").fillna(0)
    incentive_rows = b[b["transaction_type_norm"].eq(INCENTIVE_TYPE)].copy()
    actual_by_id = incentive_rows.groupby("csp_id")["actual_commission"].sum().to_dict()
    actual_rows_by_id = incentive_rows.groupby("csp_id").size().to_dict()

    # Rule 24 base is the CSP's eligible transaction-based commission, not the
    # already-paid WOMEN CSP INCENTIVE line and not the sparse verified-only
    # settlement output. The normalized BC source is the CSP-wise transaction-type
    # commission sheet; sum its eligible core commission rows by CSP, excluding
    # separate monthly incentives, non-transaction components, reimbursements and
    # penalties. Successful transaction/rate output remains an independent audit
    # cross-check, never a reason to silently zero an otherwise reported core base.
    b["transaction_type_norm"] = b["transaction_type"].map(_norm)
    # Normalize only explicit IMPS fund-transfer spelling variants. Generic
    # IMPS MONEY TRANSFER is intentionally not merged because its product slab
    # can be ambiguous in the approved rule source.
    b["transaction_type_norm"] = b["transaction_type_norm"].replace({
        "IMPS FUND TRANSFER": "IMPS FUNDTRANFER",
        "IMPS FUNDTRANSFER": "IMPS FUNDTRANFER",
        "IMPS TRANSFER": "IMPS FUNDTRANFER",
    })
    # Rule 24 only accepts known transaction/service commission types. An
    # exclusion-only filter accidentally admitted new incentive/reimbursement
    # types (and could inflate base). Explicit allowlisting is fail-closed.
    core_rows = b[b["transaction_type_norm"].isin(ELIGIBLE_BASE_TYPES)].copy()
    base_by_id = core_rows.groupby("csp_id")["actual_commission"].sum().to_dict()
    base_rows_by_id = core_rows.groupby("csp_id").size().to_dict()
    bc_name_by_id = b.drop_duplicates("csp_id").set_index("csp_id")["csp_name"].to_dict()

    r["transaction_count"] = pd.to_numeric(r["transaction_count"], errors="coerce").fillna(0)
    r["csp_name"] = r["csp_name"].fillna("").astype(str)
    rows = []
    roster_ids = set(r["csp_id"])
    for _, rr in r.iterrows():
        cid = rr["csp_id"]
        txn_count = int(rr["transaction_count"])
        base = round(float(base_by_id.get(cid, 0.0)), 2)
        expected = round(min(max(base, 0.0) * RATE, MONTHLY_CAP) + 1e-9, 2) if (txn_count > 0 or base > 0) else 0.0
        actual = round(float(actual_by_id.get(cid, 0.0)), 2)
        actual_rows = int(actual_rows_by_id.get(cid, 0))
        # Zero transaction count alone must not override a positive eligible
        # commission base and a bank-paid incentive. The approved reference has
        # one such CSP in the matched-paid category.
        if txn_count <= 0 and base <= 0 and actual <= 0:
            category = "INACTIVE ZERO-TRANSACTION CSP"
            expected = 0.0
        elif actual_rows:
            category = "MATCHED IN MASTER AND BANK" if abs(actual - expected) <= 0.02 else "AMOUNT VARIANCE"
        elif expected > 0:
            category = "UNPAID ACTIVE WOMEN CSP"
        else:
            category = "ACTIVE ZERO EXPECTED INCENTIVE"
        rows.append({
            "csp_id": cid, "csp_name": rr["csp_name"] or bc_name_by_id.get(cid, ""),
            "category": category, "transaction_count": txn_count,
            "base_transaction_commission": base, "expected_incentive": expected,
            "actual_incentive": actual, "variance_actual_minus_expected": round(actual-expected, 2),
            "actual_incentive_rows": actual_rows, "base_commission_rows": int(base_rows_by_id.get(cid, 0)),
            "in_master": True, "period": period,
        })

    # Claims paid by bank for IDs absent from the roster are not discarded: they are
    # separated for master synchronization, and their capped expectation is shown.
    extra_ids = sorted(set(incentive_rows["csp_id"]) - roster_ids)
    for cid in extra_ids:
        actual = round(float(actual_by_id.get(cid, 0.0)), 2)
        base = round(float(base_by_id.get(cid, 0.0)), 2)
        expected = round(min(max(base, 0.0) * RATE, MONTHLY_CAP) + 1e-9, 2)
        rows.append({
            "csp_id": cid, "csp_name": bc_name_by_id.get(cid, ""),
            "category": "BANK PAID — MISSING FROM WOMEN CSP MASTER", "transaction_count": None,
            "base_transaction_commission": base, "expected_incentive": expected,
            "actual_incentive": actual, "variance_actual_minus_expected": round(actual-expected, 2),
            "actual_incentive_rows": int(actual_rows_by_id.get(cid, 0)),
            "base_commission_rows": int(base_rows_by_id.get(cid, 0)), "in_master": False, "period": period,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        out = pd.DataFrame(columns=["csp_id","csp_name","category","transaction_count","base_transaction_commission","expected_incentive","actual_incentive","variance_actual_minus_expected","actual_incentive_rows","base_commission_rows","in_master","period"])
    def sum_cat(cat, col):
        s = out.loc[out["category"].eq(cat), col]
        return round(float(pd.to_numeric(s, errors="coerce").fillna(0).sum()), 2)
    matched_mask = out["category"].eq("MATCHED IN MASTER AND BANK")
    extra_mask = out["category"].eq("BANK PAID — MISSING FROM WOMEN CSP MASTER")
    unpaid_mask = out["category"].eq("UNPAID ACTIVE WOMEN CSP")
    inactive_mask = out["category"].eq("INACTIVE ZERO-TRANSACTION CSP")
    summary = {
        "total_bank_paid": round(float(incentive_rows["actual_commission"].sum()), 2),
        "bank_paid_csp_count": int(incentive_rows["csp_id"].nunique()),
        "matched_in_master_actual": round(float(out.loc[matched_mask, "actual_incentive"].sum()), 2),
        "matched_in_master_csp_count": int(matched_mask.sum()),
        "bank_paid_extra_actual": round(float(out.loc[extra_mask, "actual_incentive"].sum()), 2),
        "bank_paid_extra_expected": round(float(out.loc[extra_mask, "expected_incentive"].sum()), 2),
        "bank_paid_extra_csp_count": int(extra_mask.sum()),
        "unpaid_shortfall_expected": round(float(out.loc[unpaid_mask, "expected_incentive"].sum()), 2),
        "unpaid_shortfall_csp_count": int(unpaid_mask.sum()),
        "inactive_zero_transaction_csp_count": int(inactive_mask.sum()),
        "inactive_expected_incentive": round(float(out.loc[inactive_mask, "expected_incentive"].sum()), 2),
        "net_unclaimed_shortfall": round(float(out.loc[unpaid_mask, "variance_actual_minus_expected"].sum()), 2),
        "total_expected_for_paid_and_unpaid": round(float(out.loc[~inactive_mask, "expected_incentive"].sum()), 2),
        "base_commission_matched_in_master": round(float(out.loc[matched_mask, "base_transaction_commission"].sum()), 2),
        "base_commission_bank_extra": round(float(out.loc[extra_mask, "base_transaction_commission"].sum()), 2),
        "base_commission_unpaid_active": round(float(out.loc[unpaid_mask, "base_transaction_commission"].sum()), 2),
        "unresolved_roster_id_rows": int(len(unresolved_roster)),
        "unresolved_roster_rows": unresolved_roster.fillna("").to_dict(orient="records"),
        "out_of_roster_claims": int(extra_mask.sum()),
    }
    return {"available": True, "status": "READY", "period": period, "rule": RULE_NAME,
            "rate_percent": 10, "monthly_cap": MONTHLY_CAP,
            "formula": "min(eligible transaction-based commission × 10%, ₹1,000 per CSP/month)",
            "summary": summary, "rows": out.to_dict(orient="records"),
            "notes": ["Rule 24 base is the sum of explicitly allowlisted eligible transaction/service commission rows in the CSP-wise BC commission report; unknown types are excluded pending rule review. Successful-transaction/rate output should be used as an independent audit cross-check.",
                      "Actual Rule 24 payout is read only from the explicit WOMEN CSP INCENTIVE row.",
                      "Bank-paid CSPs missing from the roster are reported separately; their payout does not establish eligibility by itself.",
                      "Inactive zero-transaction CSPs have zero expected incentive.",
                      "Review the eligible transaction-based commission line mapping against the approved SBI rate master before settlement sign-off."]}
