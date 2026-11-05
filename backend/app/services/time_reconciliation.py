import pandas as pd
from .transaction_processor import get_successful_transactions
from .reconciliation_engine import norm, resolve_transaction_type, build_reference_type_map, canonical_key, ACCOUNT_OPEN_RULE
from .commission_engine import add_expected_commission
from .number_parser import parse_numeric_series, parse_date_series
from pathlib import Path
import hashlib, json

CACHE_DIR=Path(__file__).resolve().parents[1]/"data"/"period_cache"

def _map_tx(df, cm_df, rules):
    tx=df.copy()
    tx["csp_id"]=tx["csp_id"].map(norm)
    tx["transaction_type"]=tx["transaction_type"].map(norm)
    tx["amount"]=parse_numeric_series(tx["amount"])
    tx["transaction_date"]=parse_date_series(tx["transaction_date"])
    ref_map=build_reference_type_map(cm_df,rules)
    tx["join_type"]=[resolve_transaction_type(t,a,ref_map) for t,a in zip(tx["transaction_type"],tx["amount"])]
    tx["rule_type"]=tx["join_type"]
    tx.loc[tx["transaction_type"].eq("INITIAL DEPOSIT"),"rule_type"]=ACCOUNT_OPEN_RULE
    return tx

def _actual_by_period(cm_df, mapped_tx, grain, commission_date_granularity="date"):
    if "commission_date" not in cm_df.columns:
        return None, False
    if grain=="day" and commission_date_granularity in {"month","period"}:
        return None, False
    cm=cm_df.copy()
    cd=parse_date_series(cm["commission_date"])
    cm=cm.loc[cd.notna()].copy()
    if cm.empty:
        return None, False
    cm["commission_date"]=parse_date_series(cm["commission_date"])
    cm["csp_id"]=cm["csp_id"].map(norm)
    cm["transaction_type"]=cm["transaction_type"].map(norm)
    cm["actual_commission"]=parse_numeric_series(cm["actual_commission"])
    cm=cm[cm["actual_commission"].notna()].copy()
    if cm.empty:
        return None, True
    # Only commission categories that have a corresponding successful transaction
    # CSP + canonical type are comparable. Non-transactional BC categories remain excluded.
    ref_map=build_reference_type_map(mapped_tx[["join_type"]].rename(columns={"join_type":"transaction_type"}))
    cm["join_type"]=cm["transaction_type"].map(lambda x: ref_map.get(canonical_key(x)))
    pairs=set(zip(mapped_tx["csp_id"],mapped_tx["join_type"]))
    cm=cm[cm.apply(lambda row: (row["csp_id"],row["join_type"]) in pairs,axis=1)].copy()
    if cm.empty:
        return pd.DataFrame(columns=["period","actual_commission"]), True
    if grain=="month": cm["period"]=cm["commission_date"].dt.to_period("M").astype(str)
    else: cm["period"]=cm["commission_date"].dt.date.astype(str)
    return cm.groupby("period",as_index=False)["actual_commission"].sum(), True

def time_reconciliation(tx_df, cm_df, rules, grain="day", cache_key=None, commission_date_granularity="date", start_date=None, end_date=None, csp_id=None, transaction_type=None):
    """Return date-driven reconciliation for every day/month in the uploaded period.

    The transaction side is always derived from transaction dates. BC actuals are only
    allocated to a day/month when the commission source contains a usable commission
    date. No daily allocation is invented from an aggregated monthly BC amount.
    Optional filters are applied after normalization so the same engine works for all
    months, a custom date range, one CSP, or one transaction type.
    """
    if grain not in {"day","month"}: raise ValueError("grain must be day or month")
    tx=_map_tx(get_successful_transactions(tx_df),cm_df,rules)
    if tx.empty:
        return pd.DataFrame(columns=["period","successful_transactions","eligible_transactions","unresolved_transactions","coverage_pct","transaction_amount","expected_commission","actual_commission","variance","actual_commission_status"])

    date=parse_date_series(tx["transaction_date"])
    tx=tx.loc[date.notna()].copy()
    tx["transaction_date"]=parse_date_series(tx["transaction_date"])
    if start_date:
        sd=pd.to_datetime(start_date,errors='coerce')
        if pd.notna(sd): tx=tx.loc[tx["transaction_date"]>=sd]
    if end_date:
        ed=pd.to_datetime(end_date,errors='coerce')
        if pd.notna(ed): tx=tx.loc[tx["transaction_date"]<=ed + pd.Timedelta(days=1)-pd.Timedelta(microseconds=1)]
    if csp_id and str(csp_id).strip(): tx=tx.loc[tx["csp_id"].eq(norm(csp_id))]
    if transaction_type and str(transaction_type).strip():
        wanted=norm(transaction_type)
        tx=tx.loc[tx["join_type"].eq(wanted) | tx["transaction_type"].eq(wanted)]
    if tx.empty:
        return pd.DataFrame(columns=["period","successful_transactions","eligible_transactions","unresolved_transactions","coverage_pct","transaction_amount","expected_commission","actual_commission","variance","actual_commission_status"])

    mapped=tx[tx["join_type"].notna()].copy()
    mapped,_=add_expected_commission(mapped,rules)
    mapped["period"]=mapped["transaction_date"].dt.to_period("M").astype(str) if grain=="month" else mapped["transaction_date"].dt.date.astype(str)
    all_tx=tx.assign(period=tx["transaction_date"].dt.to_period("M").astype(str) if grain=="month" else tx["transaction_date"].dt.date.astype(str))
    total=all_tx.groupby("period",as_index=False).agg(successful_transactions=("transaction_id","size"),transaction_amount=("amount","sum"))
    if mapped.empty:
        txg=total.copy(); txg["eligible_transactions"]=0; txg["settlement_approved_transactions"]=0; txg["unresolved_transactions"]=txg["successful_transactions"]; txg["provisional_transactions"]=0; txg["coverage_pct"]=0.0; txg["settlement_coverage_pct"]=0.0; txg["expected_commission"]=pd.NA
    else:
        mapped["_calculated"] = mapped.get("rate_status",pd.Series(index=mapped.index,dtype=object)).astype('string').str.startswith("Applied") & mapped["expected_commission"].notna()
        mapped["_settlement_approved"] = mapped.get("rate_status",pd.Series(index=mapped.index,dtype=object)).eq("Applied") & mapped["expected_commission"].notna()
        mg=mapped.groupby("period",as_index=False).agg(eligible_transactions=("_calculated","sum"),settlement_approved_transactions=("_settlement_approved","sum"),expected_commission=("expected_commission",lambda x:x.sum(min_count=1)))
        txg=total.merge(mg,on="period",how="left")
        txg["eligible_transactions"]=txg["eligible_transactions"].fillna(0).astype(int)
        txg["settlement_approved_transactions"]=txg["settlement_approved_transactions"].fillna(0).astype(int)
        txg["unresolved_transactions"]=txg["successful_transactions"]-txg["eligible_transactions"]
        txg["provisional_transactions"]=txg["eligible_transactions"]-txg["settlement_approved_transactions"]
        txg["coverage_pct"]=((txg["eligible_transactions"]/txg["successful_transactions"])*100).where(txg["successful_transactions"].gt(0),0).round(2)
        txg["settlement_coverage_pct"]=((txg["settlement_approved_transactions"]/txg["successful_transactions"])*100).where(txg["successful_transactions"].gt(0),0).round(2)

    actual,available=_actual_by_period(cm_df,mapped,grain,commission_date_granularity)
    if actual is None:
        txg["actual_commission"]=pd.NA
        status="Not available by date in commission source; no daily allocation made"
    else:
        txg=txg.merge(actual,on="period",how="left")
        status="Available by date" if available else "No comparable dated commission activity"
    txg["variance"]=pd.NA
    comparable=txg["actual_commission"].notna() & txg["expected_commission"].notna() & txg["settlement_coverage_pct"].eq(100)
    txg.loc[comparable,"variance"]=pd.to_numeric(txg.loc[comparable,"expected_commission"],errors='coerce')-pd.to_numeric(txg.loc[comparable,"actual_commission"],errors='coerce')
    txg["actual_commission_status"]=status
    txg["reconciliation_status"]=txg.apply(lambda r: 'Unresolved Coverage' if float(r.get('coverage_pct',0) or 0)<100 else ('Matched' if pd.notna(r.get('variance')) and abs(float(r['variance']))<0.005 else ('Shortfall' if pd.notna(r.get('variance')) and float(r['variance'])>0 else ('Excess' if pd.notna(r.get('variance')) else 'Actual Not Comparable'))),axis=1)
    return txg.sort_values("period").reset_index(drop=True)

