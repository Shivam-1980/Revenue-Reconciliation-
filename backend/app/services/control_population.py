"""Separate real transaction populations from incentive-control base counts."""
from __future__ import annotations
import pandas as pd
from .fast_text import on_unique

SOCIAL_TYPES = {"PMJJBY", "PMSBY"}
PASSBOOK_TYPE = "PASSBOOK PRINTING"
AEPS_CASH_INCENTIVE_TYPE = "ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS"

def transaction_population_mask(rows: pd.DataFrame) -> pd.Series:
    """Mask rows that represent an independent transaction-count population."""
    if rows is None or rows.empty:
        return pd.Series(dtype=bool, index=getattr(rows, "index", None))
    supplemental = rows.get("is_supplemental", pd.Series(False, index=rows.index)).astype("boolean").fillna(False)
    typ = on_unique(rows.get("transaction_type", pd.Series("", index=rows.index)).fillna("").astype(str), lambda x: x.str.strip().str.upper().str.replace(r"\s+", " ", regex=True))
    # Include only supplemental populations with their own period-specific source.
    # CM058 is an incentive control whose base count overlaps core transactions.
    return (~supplemental) | (supplemental & (typ.isin(SOCIAL_TYPES) | typ.eq(PASSBOOK_TYPE)))


def summarize_control_population(rows: pd.DataFrame) -> dict:
    """Return counts without double-counting control-only incentive base rows.

    Rows marked supplemental are not automatically transaction populations.
    Only PMJJBY/PMSBY and Passbook Printing are added as separate source-count
    populations. CM058's report-base count is a separate incentive control and
    must not inflate successful/reconciliation population transaction totals.
    """
    if rows is None or rows.empty:
        return {"reconciliation_population_transactions": 0, "supplemental_scheme_transactions": 0,
                "social_security_supplemental_transactions": 0, "passbook_printing_supplemental_transactions": 0,
                "aeps_cash_incentive_control_transactions": 0}
    counts = pd.to_numeric(rows.get("successful_transactions", pd.Series(0, index=rows.index)), errors="coerce").fillna(0)
    supplemental = rows.get("is_supplemental", pd.Series(False, index=rows.index)).astype("boolean").fillna(False)
    typ = on_unique(rows.get("transaction_type", pd.Series("", index=rows.index)).fillna("").astype(str), lambda x: x.str.strip().str.upper().str.replace(r"\s+", " ", regex=True))
    social = supplemental & typ.isin(SOCIAL_TYPES)
    passbook = supplemental & typ.eq(PASSBOOK_TYPE)
    aeps = supplemental & typ.eq(AEPS_CASH_INCENTIVE_TYPE)
    # Non-supplemental rows include ordinary successful transaction groups and
    # explicit unresolved source groups. Control-only supplemental rows are added
    # back only when they represent independent uploaded transaction populations.
    core = ~supplemental
    social_count = int(counts.loc[social].sum())
    passbook_count = int(counts.loc[passbook].sum())
    aeps_count = int(counts.loc[aeps].sum())
    return {
        "reconciliation_population_transactions": int(counts.loc[core].sum()) + social_count + passbook_count,
        "supplemental_scheme_transactions": social_count,
        "social_security_supplemental_transactions": social_count,
        "passbook_printing_supplemental_transactions": passbook_count,
        "aeps_cash_incentive_control_transactions": aeps_count,
    }
