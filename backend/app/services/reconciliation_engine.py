import pandas as pd
import numpy as np
import re
import warnings
from functools import lru_cache
from .commission_engine import add_expected_commission
from .number_parser import parse_numeric_series, parse_date_series, map_unique
from .fast_text import on_unique
from .social_security_rules import pmjjby_rate_for_period, PMSBY_COMMISSION_PER_ENROLLMENT, PMJJBY_PREMIUM_MONTHS

BASE_DIR=__import__("pathlib").Path(__file__).resolve().parents[1]
MAPPING_MASTER_PATH=BASE_DIR / "data" / "transaction_type_mapping_master.csv"
# Optional authoritative CSP-wise social-security count source. This source is
# intentionally kept separate from transaction-level Success data because the
# supplied August PMJJBY/PMSBY workbook contains CSP-wise counts, not transaction
# references. It is used only for PMJJBY/PMSBY reconciliation when present.
SOCIAL_SECURITY_COUNTS_PATH=BASE_DIR / "data" / "supplemental" / "latest_social_security_counts.csv"
# Optional authoritative CSP-wise August passbook-printing count source. The source
# contains CSP-level monthly printing counts (not account-level references), so the
# SBI 5-print/account/month cap cannot be independently proven from this file. The
# project therefore uses it as a CSP/type count and commission control, while
# explicitly recording that the account-level cap is not verifiable from source data.
PASSBOOK_COUNTS_PATH=BASE_DIR / "data" / "supplemental" / "latest_passbook_printing_counts.csv"
# Authoritative August CSP-wise Passbook Printing reconciliation workbook-derived control.
# Contains source prints, bank-paid prints, applicable rate, expected revenue, and bank credit.
PASSBOOK_RECONCILIATION_PATH=BASE_DIR / "data" / "supplemental" / "latest_passbook_printing_reconciliation.csv"
SOCIAL_SECURITY_EXCEPTIONS_PATH=BASE_DIR / "data" / "supplemental" / "latest_social_security_counts_exceptions.csv"


def load_social_security_counts():
    """Load the approved CSP-wise PMJJBY/PMSBY count supplement for its declared period."""
    try:
        if not SOCIAL_SECURITY_COUNTS_PATH.exists():
            return pd.DataFrame()
        d=pd.read_csv(SOCIAL_SECURITY_COUNTS_PATH,dtype=str).fillna("")
        required={"csp_id","transaction_type","count","premium","period"}
        if not required.issubset(d.columns):
            return pd.DataFrame()
        d["csp_id"]=map_unique(d["csp_id"], norm)
        d["transaction_type"]=map_unique(d["transaction_type"], norm)
        d["count"]=pd.to_numeric(d["count"],errors="coerce").fillna(0)
        d["premium"]=pd.to_numeric(d["premium"],errors="coerce")
        d=d[d["csp_id"].str.match(r'^1A85\d{4}$',na=False) & d["transaction_type"].isin(["PMJJBY","PMSBY"]) & d["count"].gt(0)].copy()
        return d.groupby(["csp_id","transaction_type","premium","period"],as_index=False,dropna=False)["count"].sum()
    except Exception:
        return pd.DataFrame()

def load_social_security_count_exceptions(transaction_month=None, transaction_months=None):
    """Return malformed social-security source rows separately; never fuzzy-match CSP names."""
    empty={"available":False,"invalid_source_row_count":0,"excluded_enrollment_count":0,
           "indicative_commission_not_approved":0.0,"rows":[]}
    try:
        if not SOCIAL_SECURITY_EXCEPTIONS_PATH.exists(): return empty
        d=pd.read_csv(SOCIAL_SECURITY_EXCEPTIONS_PATH,dtype=str).fillna("")
        required={"period","transaction_type","raw_csp_code","csp_name","count","indicative_commission_not_approved","reason","resolution"}
        if not required.issubset(d.columns): return empty
        allowed=set(transaction_months or ([] if transaction_month is None else [transaction_month]))
        if allowed:
            d=d[d["period"].map(_period_month).isin(allowed)].copy()
        elif len(d["period"].map(_period_month).dropna().unique()) == 1:
            # Single-period audit supplement may be surfaced when no transaction month is passed.
            pass
        else:
            return empty
        if d.empty: return empty
        d["count"]=pd.to_numeric(d["count"],errors="coerce").fillna(0)
        d["indicative_commission_not_approved"]=pd.to_numeric(d["indicative_commission_not_approved"],errors="coerce").fillna(0)
        return {"available":True,"invalid_source_row_count":int(len(d)),
                "excluded_enrollment_count":int(d["count"].sum()),
                "indicative_commission_not_approved":round(float(d["indicative_commission_not_approved"].sum()),2),
                "rows":d.to_dict(orient="records")}
    except Exception:
        return empty

def load_passbook_printing_counts():
    """Load CSP-wise passbook counts for any declared period; bank POPULATION is authoritative."""
    try:
        if not PASSBOOK_COUNTS_PATH.exists():
            return pd.DataFrame()
        d=pd.read_csv(PASSBOOK_COUNTS_PATH,dtype=str).fillna("")
        required={"csp_id","transaction_type","count","period"}
        if not required.issubset(d.columns):
            return pd.DataFrame()
        d["csp_id"]=map_unique(d["csp_id"], norm)
        d["transaction_type"]=map_unique(d["transaction_type"], norm)
        d["count"]=pd.to_numeric(d["count"],errors="coerce")
        if "rate" not in d.columns: d["rate"]=pd.NA
        if "population" not in d.columns: d["population"]=""
        d["rate"]=pd.to_numeric(d["rate"],errors="coerce")
        d["population"]=map_unique(d["population"], norm)
        d=d[d["csp_id"].str.match(r'^1A85\d{4}$',na=False) & d["transaction_type"].eq("PASSBOOK PRINTING") & d["count"].gt(0) & d["period"].astype(str).str.strip().ne("")].copy()
        return d.groupby(["csp_id","transaction_type","population","rate","period"],as_index=False,dropna=False)["count"].sum()
    except Exception:
        return pd.DataFrame()


def load_passbook_printing_reconciliation(transaction_month=None):
    """Load a passbook control workbook only when its explicit period matches the run."""
    try:
        if not PASSBOOK_RECONCILIATION_PATH.exists():
            return pd.DataFrame()
        d=pd.read_csv(PASSBOOK_RECONCILIATION_PATH,dtype=str).fillna("")
        required={"csp_id","source_count","bank_count","population","rate","expected_commission","actual_commission","count_difference","revenue_difference_bank_minus_expected","period"}
        if not required.issubset(d.columns) or not transaction_month:
            return pd.DataFrame()
        d=d[d["period"].map(_period_month).eq(transaction_month)].copy()
        if d.empty:
            return pd.DataFrame()
        d["csp_id"]=map_unique(d["csp_id"], norm)
        for c in ["source_count","bank_count","rate","expected_commission","actual_commission","count_difference","revenue_difference_bank_minus_expected"]:
            d[c]=pd.to_numeric(d[c],errors="coerce")
        d["population"]=map_unique(d["population"], norm)
        d=d[d["csp_id"].str.match(r'^1A85\d{4}$',na=False) & d["source_count"].notna()].copy()
        return d
    except Exception:
        return pd.DataFrame()

def _transaction_months_from_transactions(transactions):
    """Return sorted YYYY-MM periods represented by valid transaction dates."""
    if transactions is None or transactions.empty or "transaction_date" not in transactions.columns:
        return []
    d=parse_date_series(transactions["transaction_date"]).dropna()
    if d.empty:
        return []
    return sorted(d.dt.to_period("M").astype(str).unique().tolist())


def _single_calendar_month_from_transactions(transactions):
    """Return YYYY-MM only when the uploaded transaction source is wholly in one month."""
    months = _transaction_months_from_transactions(transactions)
    return months[0] if len(months) == 1 else None

def _period_month(period_value):
    """Normalize a supplemental period label/date to YYYY-MM."""
    if period_value is None:
        return None
    raw=str(period_value).strip()
    if not raw:
        return None
    return _period_month_of_text(raw)

@lru_cache(maxsize=4096)
def _period_month_of_text(raw):
    """The same label is parsed thousands of times per run: parse each distinct text once."""
    parsed=pd.to_datetime(raw,errors="coerce",dayfirst=False)
    if pd.notna(parsed):
        return parsed.strftime("%Y-%m")
    # Handles labels such as 'AUGUST 2026', 'Sep-2026', etc.
    for fmt in ["%B %Y","%b %Y","%B-%Y","%b-%Y"]:
        try:
            return pd.to_datetime(raw,format=fmt).strftime("%Y-%m")
        except Exception:
            pass
    return None

def _supplement_periods_match(d, transaction_month=None, transaction_months=None):
    """Only activate supplemental rows whose periods are represented in the run.

    `transaction_month` preserves the original single-period API. For a multi-month
    transaction file callers can pass `transaction_months`; every supplemental row
    must have an explicit, parseable period included in that set. This prevents stale
    periods leaking into a run while allowing correct multi-month reconciliation.
    """
    if d is None or d.empty or 'period' not in d.columns:
        return False
    allowed = set(transaction_months or ([] if transaction_month is None else [transaction_month]))
    if not allowed:
        return False
    periods = d['period'].map(_period_month)
    present = set(periods.dropna().tolist())
    # Require complete period coverage. A supplement containing only August rows
    # must not be treated as a complete August+September source merely because all
    # its rows are technically inside the requested range.
    return bool(periods.notna().all() and present.issubset(allowed) and allowed.issubset(present))


def passbook_supplement_active(d, transaction_month=None, transaction_months=None):
    return (d is not None and not d.empty
            and set(map_unique(d["transaction_type"], norm).unique()).issubset({"PASSBOOK PRINTING"})
            and _supplement_periods_match(d, transaction_month, transaction_months))

def social_security_supplement_active(d, transaction_month=None, transaction_months=None):
    return (d is not None and not d.empty
            and set(map_unique(d["transaction_type"], norm).unique()).issubset({"PMJJBY","PMSBY"})
            and _supplement_periods_match(d, transaction_month, transaction_months))

def _pmjjby_rate_for_period(period_value):
    """Compatibility wrapper around the centralized, source-documented rule."""
    return pmjjby_rate_for_period(period_value)


# Non-transactional BC report categories must not be treated as transaction counts.
# This is a classification/control layer only; it never changes the reported commission.
NON_TRANSACTIONAL_BC_TYPES={
    "AVERAGE BALANCE MAINTENANCE", "RURAL COMMISSION", "WOMEN CSP INCENTIVE",
    "ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS", "DFS PRIORITIES INCENTIVE",
    "PASSBOOK PRINTER COST REIMBURSEMENT", "PENALTY FOR CSP INACTIVITY",
    "LAKSHYA DEPOSIT MOBILISATION CAMPAIGN INCENTIVE", "WOMEN CSP INCENTIVE",
    "MATM CASH TRANSACTIONS INCENTIVE", "TAB FINANCIAL TRANSACTIONS INCENTIVE", "TAB TRANSACTIONS INCENTIVE",
    "5 STAR INCENTIVE", "RURAL CSP COMMISSION", "AVERAGE BALANCE MAINTENANCE COMMISSION",
}

@lru_cache(maxsize=4)
def _load_transaction_mapping_master_cached(mtime_ns):
    """Cached mapping master; cache key changes automatically when the CSV changes."""
    out={}
    try:
        if MAPPING_MASTER_PATH.exists():
            m=pd.read_csv(MAPPING_MASTER_PATH,dtype=str).fillna("")
            for src,bc,status in zip(m.get("source_transaction_type",[]),m.get("bc_transaction_type",[]),m.get("status",[])):
                src=norm(src); bc=norm(bc)
                if src and bc and norm(status) not in {"UNMAPPED","BLOCKED"}:
                    out[src]=bc
    except Exception:
        pass
    out.update({k:v for k,v in TYPE_MAPPING.items() if k not in out})
    return out

def load_transaction_mapping_master():
    """Load the editable transaction mapping master once per file version."""
    try: mtime=MAPPING_MASTER_PATH.stat().st_mtime_ns if MAPPING_MASTER_PATH.exists() else 0
    except Exception: mtime=0
    return _load_transaction_mapping_master_cached(mtime)

@lru_cache(maxsize=4)
def _load_mapping_confidence_cached(mtime_ns):
    out={}
    try:
        if MAPPING_MASTER_PATH.exists():
            m=pd.read_csv(MAPPING_MASTER_PATH,dtype=str).fillna("")
            for src,status in zip(m.get('source_transaction_type',[]),m.get('status',[])):
                out[norm(src)]=norm(status) or 'UNMAPPED'
    except Exception:
        pass
    return out

@lru_cache(maxsize=4)
def _load_explicit_mapping_status_cached(mtime_ns):
    out={}
    try:
        if MAPPING_MASTER_PATH.exists():
            m=pd.read_csv(MAPPING_MASTER_PATH,dtype=str).fillna("")
            for src,status in zip(m.get("source_transaction_type",[]),m.get("status",[])):
                src=norm(src); status=norm(status)
                if src: out[src]=status
    except Exception:
        pass
    return out

def _get_explicit_mapping_status(source_transaction_type):
    try: mtime=MAPPING_MASTER_PATH.stat().st_mtime_ns if MAPPING_MASTER_PATH.exists() else 0
    except Exception: mtime=0
    return _load_explicit_mapping_status_cached(mtime).get(norm(source_transaction_type))

def get_mapping_confidence(source_transaction_type):
    """Return the source mapping confidence from the controlled mapping master."""
    t=norm(source_transaction_type)
    if not t: return "UNMAPPED"
    try: mtime=MAPPING_MASTER_PATH.stat().st_mtime_ns if MAPPING_MASTER_PATH.exists() else 0
    except Exception: mtime=0
    meta=_load_mapping_confidence_cached(mtime)
    if t in meta: return meta[t]
    if t in TYPE_MAPPING: return "EXACT"
    if t in {"INITIAL DEPOSIT","CUSTOMER ENROLL FOR SSS"}: return "CONDITIONAL"
    return "UNMAPPED"

def classify_bc_measurement_type(transaction_type):
    t=norm(transaction_type)
    if not t:
        return "UNCLASSIFIED"
    if t in NON_TRANSACTIONAL_BC_TYPES:
        return "INCENTIVE" if "INCENTIVE" in t or "COMMISSION" in t or "REIMBURSEMENT" in t else ("PENALTY" if "PENALTY" in t else "AVERAGE_BALANCE" if "BALANCE" in t else "FIXED_AMOUNT")
    # Known operational/commission transaction categories represent transaction counts.
    known=set(load_transaction_mapping_master().values()) | set(ACCOUNT_OPEN_TYPES.values()) | {"PMSBY","PMJJBY","PASSBOOK PRINTING","CASH WITHDRAWAL","CASH DEPOSIT","MONEY TRANSFER","STDR OPEN","LOAN DEPOSIT"}
    if t in known or t.startswith("ACC OPEN WITH EKYC"):
        return "TRANSACTION_COUNT"
    return "UNCLASSIFIED"

# Approved transaction-type mapping for the current SBI/Eko operating model.
# Unknown labels are NEVER guessed; they become explicit exceptions until the mapping master is updated.
TYPE_MAPPING={
'MONEY TRANSFER':'MONEY TRANSFER','AEPS ONUS WITHDRAWAL':'AEPS ONUS WITHDRAWAL','AEPS ONUS DEPOSIT':'AEPS ONUS DEPOSIT',
'WITHDRAWAL':'CASH WITHDRAWAL','AEPS OFFUS WITHDRAWAL':'AEPS ACQUIRER WITHDRAWAL','ATM ONUS WITHDRAWAL':'DEBIT CARD ONUS',
'ATM OFFUS WITHDRAWAL':'DEBIT CARD OFFUS','ATM DEPOSIT':'MATM ONUS DEPOSIT','ATM FUNDSTRANSFER':'MATM ONUS FUNDSTRANSFER - HOME',
'DEPOSIT':'CASH DEPOSIT','FUND TRANSFER':'FUNDTRANSFER - HOME','IMPS FUND TRANSFER':'IMPS TRANSFER','IMPS FUNDTRANSFER':'IMPS TRANSFER','IMPS FUNDTRANFER':'IMPS TRANSFER',
'IMPS MONEY TRANSFER':'IMPS MONEY TRANSFER','IMPS - CASH':'IMPS CASH','IMPS CASH':'IMPS CASH','IMPS - TRANSFER':'IMPS TRANSFER','IMPS TRANSFER':'IMPS TRANSFER','STDR OPEN':'STDR OPEN','OPENING STDR/FD':'STDR OPEN','OPENING OF STDR/FD':'STDR OPEN','STDR/FD OPEN':'STDR OPEN','STDR FD OPEN':'STDR OPEN','FIXED DEPOSIT OPEN':'STDR OPEN','YONO WITHDRAWAL':'YONO CASH',
'BHARAT BILL PAYMENTS':'BBPS - ELECTRICITY','LOAN DEPOSIT':'LOAN DEPOSIT','AEPS ONUS FUND TRANSFER':'AEPS ONUS FUNDTRANSFER - HOME'
}
ACCOUNT_OPEN_TYPES={
    'BELOW':'ACC OPEN WITH EKYC AND INIT DEP BELOW 100',
    '100_499':'ACC OPEN WITH EKYC AND INIT DEP BTWN 100 AND 499',
    '500_999':'ACC OPEN WITH EKYC AND INIT DEP BTWN 500 AND 999',
    '1000_PLUS':'ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE'
}
ACCOUNT_OPEN_RULE='ACCOUNT OPPENING (PMJDY)'
# Source labels that the bank reports on a line of their own although they share a rate rule with another label.
BC_OWN_LINE_TYPES={'MONEY TRANSFER'}


def canonical_key(value):
    """Deterministic comparison key: case/space/punctuation insensitive, never fuzzy."""
    return re.sub(r'[^A-Z0-9]+','',norm(value))

def build_reference_type_map(*frames):
    """Build exact/canonical lookup from uploaded commercial/reporting types."""
    out={}
    for frame in frames:
        if frame is None or 'transaction_type' not in frame.columns: continue
        for value in frame['transaction_type'].dropna().astype(str):
            n=norm(value)
            if not n: continue
            out.setdefault(canonical_key(n), n)
    return out

def resolve_transaction_type(tx_type, amount=None, reference_map=None, transaction_date=None):
    """Resolve a transaction label without fuzzy guessing.

    Order: approved operational mapping -> exact uploaded reference type ->
    punctuation/space-insensitive exact match. Unknown labels stay unmapped.
    """
    t=norm(tx_type)
    # Explicit approved STDR/FD aliases; no fuzzy matching.
    if t in {'OPENING STDR/FD','OPENING OF STDR/FD','STDR/FD OPEN','STDR FD OPEN','FIXED DEPOSIT OPEN'}:
        return 'STDR OPEN'
    if t=='INITIAL DEPOSIT':
        # Prefer the exact bucket vocabulary present in the BC report. If the
        # report instead aggregates account opening under the parent commercial
        # product, fall back to the parent rule so the engine remains reusable.
        try: a=float(amount)
        except Exception: return None
        if pd.isna(a): return None
        bucket = ('ACC OPEN WITH EKYC AND INIT DEP BELOW 100' if a < 100 else
                  'ACC OPEN WITH EKYC AND INIT DEP BTWN 100 AND 499' if a < 500 else
                  'ACC OPEN WITH EKYC AND INIT DEP BTWN 500 AND 999' if a < 1000 else
                  'ACC OPEN WITH EKYC AND INIT DEP 1000 OR ABOVE')
        if reference_map and canonical_key(bucket) in reference_map: return reference_map[canonical_key(bucket)]
        if reference_map and canonical_key(ACCOUNT_OPEN_RULE) in reference_map: return reference_map[canonical_key(ACCOUNT_OPEN_RULE)]
        return bucket
    if t=='CUSTOMER ENROLL FOR SSS':
        # PMJJBY premium is quarter-specific in the SBI PDF; PMSBY is Rs 20.
        try: a=float(amount)
        except Exception: return None
        if pd.isna(a): return None
        month = None
        if transaction_date is not None and not pd.isna(transaction_date):
            try: month=int(pd.Timestamp(transaction_date).month)
            except Exception: month=None
        candidate=None
        if abs(a-20.0) < 0.005:
            candidate='PMSBY'
        else:
            premium_months=PMJJBY_PREMIUM_MONTHS
            for premium,months in premium_months.items():
                if abs(a-premium)<0.005 and (month is None or month in months):
                    candidate='PMJJBY'; break
        if candidate and reference_map and canonical_key(candidate) in reference_map: return reference_map[canonical_key(candidate)]
        return candidate
    # An explicit UNMAPPED/BLOCKED row in the controlled mapping master is a
    # hard stop. Do not let an exact label appearing incidentally in an uploaded
    # rate/report vocabulary bypass the approved mapping decision. Unknown labels
    # that have no mapping-master row may still use exact reference-vocabulary
    # matching for month-agnostic extensibility.
    # Use the mtime-cached explicit-status lookup: this function is called once
    # per source row, so re-reading the CSV here would make large monthly uploads
    # unnecessarily slow. A label absent from the master may still use exact
    # uploaded reference vocabulary; only an explicit UNMAPPED/BLOCKED row is a hard stop.
    if _get_explicit_mapping_status(t) in {"UNMAPPED", "BLOCKED"}:
        return None
    mapped=load_transaction_mapping_master().get(t)
    if mapped: return mapped
    if reference_map:
        return reference_map.get(canonical_key(t))
    return None

def map_transaction(tx_type, amount):
    t=norm(tx_type)
    resolved=resolve_transaction_type(t, amount)
    return resolved, resolved


def resolve_transaction_types_series(types, amounts, dates, reference_map):
    """Resolve labels by unique source type, retaining row-level rules only where needed.

    Most transaction-type mappings depend only on the source label. Calling the
    resolver for every row repeatedly stats/loads mapping metadata and normalizes
    identical strings hundreds of thousands of times. Only INITIAL DEPOSIT and
    CUSTOMER ENROLL FOR SSS depend on row amount/date, so those keep row-wise logic.
    """
    source = map_unique(types, norm)
    out = pd.Series(pd.NA, index=types.index, dtype='object')
    variable = source.isin(['INITIAL DEPOSIT', 'CUSTOMER ENROLL FOR SSS'])
    fixed_types = source.loc[~variable].dropna().unique()
    lookup = {t: resolve_transaction_type(t, None, reference_map, None) for t in fixed_types}
    out.loc[~variable] = source.loc[~variable].map(lookup)
    if variable.any():
        vals = zip(source.loc[variable], amounts.loc[variable], dates.loc[variable])
        out.loc[variable] = [resolve_transaction_type(t, a, reference_map, d) for t, a, d in vals]
    return out


def mapping_confidence_series(types):
    """Look up confidence once per distinct source label, not once per transaction."""
    normalized = map_unique(types, norm)
    lookup = {t: get_mapping_confidence(t) for t in normalized.dropna().unique()}
    return normalized.map(lookup).fillna('UNMAPPED')

@lru_cache(maxsize=65536)
def _norm_text(v):
    return ' '.join(v.strip().upper().split())

def norm(v):
    # Called once per row on large uploads; string results are cached (same output as before).
    if type(v) is str: return _norm_text(v)
    if pd.isna(v): return ''
    return ' '.join(str(v).strip().upper().split())

def _rate_master(path):
    try: return pd.read_csv(path,low_memory=False)
    except Exception: return None

def reconcile_transactions(transactions, commission, rate_rules=None, social_security_counts=None, passbook_printing_counts=None):
    """Reconcile successful transactions against the aggregated BC commission report.

    Accounting policy:
    - Expected commission comes ONLY from the approved rate/slab master.
    - Actual commission is matched on CSP + canonical transaction type because the
      supplied BC report is aggregated and has no transaction reference.
    - Monetary gap is calculated only for transaction groups for which an approved
      rate rule was actually applied. Unresolved commercial rules are never treated
      as zero and are excluded from the monetary gap while remaining visible as
      exceptions.
    - Count variance and monetary gap are separate controls.
    """
    tx=transactions.copy()
    tx['csp_id']=map_unique(tx['csp_id'], norm)
    tx['transaction_type']=map_unique(tx['transaction_type'], norm)
    if 'kyc_type' in tx.columns:
        from .rate_master import _normalize_kyc
        tx['kyc_type']=tx['kyc_type'].map(_normalize_kyc)
    else:
        tx['kyc_type']=''
    tx['amount']=parse_numeric_series(tx['amount'])
    tx['transaction_date']=parse_date_series(tx['transaction_date']) if 'transaction_date' in tx else pd.NaT
    # The uploaded rate master and BC report are both valid reference vocabularies.
    # Exact matching against them lets future months introduce new transaction labels
    # without editing Python, while deliberately avoiding fuzzy/guess matching.
    cm_ref=build_reference_type_map(commission)
    rm_ref=build_reference_type_map(rate_rules) if rate_rules is not None else {}
    ref_map=dict(cm_ref)
    ref_map.update({k:v for k,v in rm_ref.items() if k not in ref_map})
    tx['join_type']=resolve_transaction_types_series(tx['transaction_type'],tx['amount'],tx['transaction_date'],ref_map)
    tx['mapping_confidence']=mapping_confidence_series(tx['transaction_type'])
    tx['rule_type']=tx['join_type']
    tx['bc_join_type']=tx['join_type']
    # MONEY TRANSFER and FUND TRANSFER both resolve to the same commercial rule (FUNDTRANSFER - HOME) but the bank pays and
    # reports them as two separate lines. Join the bank report on the label the bank uses, otherwise one CSP's combined actual
    # is copied onto both rows (double-counted).
    tx.loc[tx['transaction_type'].isin(BC_OWN_LINE_TYPES),'bc_join_type']=tx['transaction_type']
    # Customer enroll for SSS is a successful-source product classification used
    # for PMJJBY/PMSBY rule calculation, but the mapping workbook explicitly says
    # there is no equivalent BC transaction type. Keep it out of BC settlement joins.
    tx.loc[tx['transaction_type'].eq('CUSTOMER ENROLL FOR SSS'),'bc_join_type']=pd.NA
    tx.loc[tx['transaction_type'].eq('INITIAL DEPOSIT'),'rule_type']=ACCOUNT_OPEN_RULE
    tx['successful_transactions']=1
    tx['transaction_amount']=tx['amount'].fillna(0)

    mapped_tx=tx[tx['join_type'].notna()].copy()
    if rate_rules is not None and not rate_rules.empty:
        mapped_tx,rate_info=add_expected_commission(mapped_tx,rate_rules)
    else:
        mapped_tx,rate_info=add_expected_commission(mapped_tx,None)
    for c in ['expected_commission','commission_rule_id','rate_status','rule_exists','condition_failure','required_evidence_missing','condition_fail_reason']:
        if c not in mapped_tx.columns: mapped_tx[c]=pd.NA
    tx.loc[mapped_tx.index,['expected_commission','commission_rule_id','rate_status','rule_exists','condition_failure','required_evidence_missing','condition_fail_reason']]=mapped_tx[['expected_commission','commission_rule_id','rate_status','rule_exists','condition_failure','required_evidence_missing','condition_fail_reason']]
    tx['expected_commission']=pd.to_numeric(tx.get('expected_commission'),errors='coerce')
    tx['condition_fail_transactions']=pd.to_numeric(tx.get('condition_failure'),errors='coerce').fillna(0).astype(int)
    tx['expected_transaction_rows']=tx['expected_commission'].notna().astype(int)
    # Verified expected commission is stricter than calculated/provisional expected:
    # only a confirmed, uniquely matched SBI rule is included. Mapping-to-confirm
    # and unresolved geography remain visible but are not silently added to the
    # monthly verified total.
    # Final verified expected commission requires both a deterministic SBI rule
    # and all transaction-level eligibility evidence available in the source.
    verified_mask=(
        on_unique(tx['rate_status'].astype('string'), lambda x: x.str.startswith('Applied')) &
        ~on_unique(tx['rate_status'].astype('string'), lambda x: x.str.contains('Pending Mapping',na=False)) &
        on_unique(tx['mapping_confidence'].astype('string'), lambda x: x.str.upper()).eq('EXACT')
    )
    # V54: the user supplied an explicit SBI product-rule schedule for PMJDY,
    # PMJJBY and PMSBY. For these products the expected amount can therefore be
    # verified from the transaction amount/month mapping and the supplied rule;
    # do not block the calculation merely because the older master lacked an
    # explicit e-KYC/eligibility flag. Unknown/unclassifiable SSS premiums still
    # remain unmapped and are never guessed.
    # BBPS needs biller category/CCF to select the correct SBI product rule.
    verified_mask &= ~tx['transaction_type'].eq('BHARAT BILL PAYMENTS')
    tx['verified_expected_commission']=tx['expected_commission'].where(verified_mask)
    tx['expected_commission_low']=tx['expected_commission']
    tx['expected_commission_high']=tx['expected_commission']
    tx['geography_status']=on_unique(tx['rate_status'].astype('string'), lambda x: x.map(lambda v: 'Resolved' if str(v).startswith('Applied') else 'Unresolved'))

    # Geography is never inferred. If the uploaded transaction/commission source
    # does not provide CSP Rural/Urban and the SBI rule has different payouts, the
    # row remains unresolved/conditional. This prevents a synthetic scenario range
    # from being mistaken for a final expected commission.
    # Per-row flags are computed once, vectorized, so the groupby uses built-in
    # aggregations instead of one Python call per group (V62.6.205 performance).
    joined=tx[tx['join_type'].notna()].copy()
    rate_status=joined['rate_status'].astype('string')
    joined['_geo_unresolved']=on_unique(joined['geography_status'].astype('string'), lambda x: x.str.startswith('Scenario range')).fillna(False).astype(int)
    joined['_rate_missing']=rate_status.eq('Rate Master Missing').fillna(False).astype(int)
    joined['_rate_ambiguous']=rate_status.eq('Ambiguous Rate Rule').fillna(False).astype(int)
    joined['_rate_applied']=on_unique(rate_status, lambda x: x.str.startswith('Applied')).fillna(False).astype(int)
    joined['_rate_pending']=on_unique(rate_status, lambda x: x.str.contains('Pending Mapping',na=False)).fillna(False).astype(int)
    txg=_group_aggregate(joined,['csp_id','transaction_type','join_type','bc_join_type'],[
        ('mapping_confidence','mapping_confidence','first'),
        ('successful_transactions','successful_transactions','sum'),
        ('transaction_amount','transaction_amount','sum'),
        ('expected_commission','expected_commission','sum_min1'),
        ('verified_expected_commission','verified_expected_commission','sum_min1'),
        ('expected_commission_low','expected_commission_low','sum_min1'),
        ('expected_commission_high','expected_commission_high','sum_min1'),
        ('geography_unresolved_transactions','_geo_unresolved','sum'),
        ('rate_rule_missing','_rate_missing','sum'),
        ('rate_rule_ambiguous','_rate_ambiguous','sum'),
        ('rate_rule_applied','_rate_applied','sum'),
        ('rate_rule_pending','_rate_pending','sum'),
        ('rate_rule_geography_resolved','_rate_applied','sum'),
        ('condition_fail_transactions','condition_fail_transactions','sum'),
        ('required_evidence_transactions','required_evidence_missing','sum'),
        ('expected_transaction_rows','expected_transaction_rows','sum'),
    ])
    txg['is_supplemental']=False

    # CM058 — Additional Incentive on AEPS Cash Transactions (₹1 each).
    # The supplied rule says 'Per AEPS cash transaction' but does not enumerate
    # eligible subtypes. Use withdrawal types in the current mapping; do not infer
    # deposits/fund transfers. This separate CSP-level incentive control does not
    # change the homogeneous transaction-count KPI population.
    CM058_ELIGIBLE_SOURCE_TYPES = {
        'AEPS ONUS WITHDRAWAL',
        'AEPS OFFUS WITHDRAWAL',
        'AEPS ACQUIRER WITHDRAWAL',
    }
    cm058_src = tx[tx['transaction_type'].isin(CM058_ELIGIBLE_SOURCE_TYPES)].copy()
    if not cm058_src.empty:
        cm058_rows = cm058_src.groupby('csp_id', as_index=False, dropna=False).agg(
            successful_transactions=('successful_transactions','sum'),
            transaction_amount=('transaction_amount','sum')
        )
        cm058_rows['transaction_type']='ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS'
        cm058_rows['join_type']='ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS'
        cm058_rows['bc_join_type']='ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS'
        cm058_rows['mapping_confidence']='EXACT'
        cm058_rows['expected_commission']=pd.to_numeric(cm058_rows['successful_transactions'],errors='coerce') * 1.0
        cm058_rows['verified_expected_commission']=cm058_rows['expected_commission']
        cm058_rows['expected_commission_low']=cm058_rows['expected_commission']
        cm058_rows['expected_commission_high']=cm058_rows['expected_commission']
        cm058_rows['geography_unresolved_transactions']=0
        cm058_rows['rate_rule_missing']=0
        cm058_rows['rate_rule_ambiguous']=0
        cm058_rows['rate_rule_applied']=cm058_rows['successful_transactions']
        cm058_rows['rate_rule_pending']=0
        cm058_rows['rate_rule_geography_resolved']=cm058_rows['successful_transactions']
        cm058_rows['condition_fail_transactions']=0
        cm058_rows['required_evidence_transactions']=0
        cm058_rows['expected_transaction_rows']=cm058_rows['successful_transactions']
        cm058_rows['commission_rule_id']='CM058'
        cm058_rows['is_supplemental']=True
        for col in txg.columns:
            if col not in cm058_rows.columns:
                cm058_rows[col]=pd.NA
        cm058_rows=cm058_rows[txg.columns]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FutureWarning)
            txg=pd.concat([txg,cm058_rows],ignore_index=True,sort=False)

    # August PMJJBY/PMSBY is supplied as a CSP-wise count workbook rather than
    # transaction-level references. When that authoritative supplement is present,
    # replace the older 95-row `Customer enroll for SSS` population for these two
    # products at the reconciliation-group level. This prevents under-counting the
    # schemes while never fabricating transaction references.
    ss = social_security_counts if social_security_counts is not None else pd.DataFrame()
    transaction_months = _transaction_months_from_transactions(transactions)
    transaction_month = transaction_months[0] if len(transaction_months) == 1 else None
    if social_security_supplement_active(ss, transaction_month, transaction_months):
        txg=txg[~txg['transaction_type'].isin(['PMJJBY','PMSBY'])].copy()
        txg=txg[~txg['transaction_type'].eq('CUSTOMER ENROLL FOR SSS')].copy()
        ss_rows=ss.copy()
        ss_rows['join_type']=ss_rows['transaction_type']
        ss_rows['bc_join_type']=ss_rows['transaction_type']
        ss_rows['mapping_confidence']='EXACT'
        ss_rows['successful_transactions']=ss_rows['count'].astype(int)
        ss_rows['transaction_amount']=ss_rows['count']*ss_rows['premium']
        # Missing premium is not imputed: expected commission remains count × approved rate,
        # while transaction amount stays unknown for audit transparency.
        ss_rows['expected_commission']=ss_rows['count'] * ss_rows.apply(
            lambda z: (_pmjjby_rate_for_period(z['period']) if z['transaction_type']=='PMJJBY' else (PMSBY_COMMISSION_PER_ENROLLMENT if z['transaction_type']=='PMSBY' else pd.NA)), axis=1
        )
        # The PMJJBY/PMSBY August rules are explicitly present in the approved
        # rate master. Keep the calculation deterministic and auditable.
        ss_rows['verified_expected_commission']=ss_rows['expected_commission']
        ss_rows['expected_commission_low']=ss_rows['expected_commission']
        ss_rows['expected_commission_high']=ss_rows['expected_commission']
        ss_rows['geography_unresolved_transactions']=0
        ss_rows['rate_rule_missing']=0
        ss_rows['rate_rule_ambiguous']=0
        ss_rows['rate_rule_applied']=ss_rows['successful_transactions']
        ss_rows['rate_rule_pending']=0
        ss_rows['rate_rule_geography_resolved']=ss_rows['successful_transactions']
        ss_rows['condition_fail_transactions']=0
        ss_rows['required_evidence_transactions']=0
        ss_rows['expected_transaction_rows']=ss_rows['successful_transactions']
        ss_rows['commission_rule_id']=ss_rows['transaction_type'].map({'PMJJBY':'CM026','PMSBY':'CM030'})
        ss_rows['is_supplemental']=True
        # Apply each month's rate first, then combine periods into one CSP/product
        # reconciliation row so monthly source rows don't duplicate actual payout.
        ss_rows=ss_rows.groupby(['csp_id','transaction_type','join_type','bc_join_type'],as_index=False,dropna=False).agg(
            mapping_confidence=('mapping_confidence','first'),
            successful_transactions=('successful_transactions','sum'),
            transaction_amount=('transaction_amount','sum'),
            expected_commission=('expected_commission',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
            verified_expected_commission=('verified_expected_commission',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
            expected_commission_low=('expected_commission_low',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
            expected_commission_high=('expected_commission_high',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
            geography_unresolved_transactions=('geography_unresolved_transactions','sum'),
            rate_rule_missing=('rate_rule_missing','sum'), rate_rule_ambiguous=('rate_rule_ambiguous','sum'),
            rate_rule_applied=('rate_rule_applied','sum'), rate_rule_pending=('rate_rule_pending','sum'),
            rate_rule_geography_resolved=('rate_rule_geography_resolved','sum'),
            condition_fail_transactions=('condition_fail_transactions','sum'),
            required_evidence_transactions=('required_evidence_transactions','sum'),
            expected_transaction_rows=('expected_transaction_rows','sum'),
            commission_rule_id=('commission_rule_id','first'), is_supplemental=('is_supplemental','first'))
        txg=pd.concat([txg,ss_rows],ignore_index=True,sort=False)

    # Passbook Printing is supplied as a CSP-wise count workbook. It is a
    # separate control population because the source has no account/reference IDs.
    # The rate is authoritative from CSP geography: Rural/Semi Urban = Rs 5 and
    # Urban/Metro = Rs 6. The SBI five-print/account/month cap remains explicitly
    # unverified because account-level data is not present in the supplied source.
    pb = passbook_printing_counts if passbook_printing_counts is not None else pd.DataFrame()
    if passbook_supplement_active(pb, transaction_month, transaction_months):
        txg=txg[~txg['transaction_type'].eq('PASSBOOK PRINTING')].copy()
        pb_rows=pb.copy()
        pb_rows['join_type']='PASSBOOK PRINTING'
        pb_rows['bc_join_type']='PASSBOOK PRINTING'
        pb_rows['mapping_confidence']='EXACT'
        pb_rows['successful_transactions']=pb_rows['count'].astype(int)
        pb_rows['transaction_amount']=0.0

        # IMPORTANT CONTROL: Passbook expected revenue is calculated from the approved
        # SBI rate master, not from the rate embedded in the supplemental CSV. The
        # supplemental rate is only a source-validation field. This prevents a stale
        # or manually edited source rate from changing settlement logic.
        # The approved geography must come from the current BC commission workbook's
        # Payment Status.POPULATION (normalized to channel during upload), never from
        # a supplemental print-count workbook or a stale rate column.
        cm_geo=commission.copy()
        if 'channel' in cm_geo.columns:
            cm_geo['csp_id']=map_unique(cm_geo['csp_id'], norm)
            cm_geo['channel']=cm_geo['channel'].map(lambda x: norm(x).replace('SEMI-URBAN','RURAL').replace('SEMI URBAN','RURAL').replace('METRO','URBAN').replace('URBAN/METRO','URBAN'))
            geo_lookup={}
            for _csp,_g in cm_geo.groupby('csp_id'):
                _vals=set(_g['channel'].dropna().tolist())-{''}
                geo_lookup[_csp]=next(iter(_vals)) if len(_vals)==1 else ('CONFLICT' if _vals else '')
            pb_rows['population']=pb_rows['csp_id'].map(lambda x: geo_lookup.get(norm(x),''))
        else:
            pb_rows['population']=''
        pb_rows['population']=pb_rows['population'].map(lambda x: norm(x).replace('SEMI-URBAN','RURAL').replace('SEMI URBAN','RURAL').replace('METRO','URBAN').replace('URBAN/METRO','URBAN'))
        pb_rule_rows = pd.DataFrame()
        if rate_rules is not None and not rate_rules.empty:
            pb_rule_rows=rate_rules[map_unique(rate_rules['transaction_type'], norm).eq('PASSBOOK PRINTING')].copy()
            if not pb_rule_rows.empty:
                pb_rule_rows['channel_norm']=map_unique(pb_rule_rows['channel'], norm) if 'channel' in pb_rule_rows.columns else ''
                pb_rule_rows['rate_num']=pd.to_numeric(pb_rule_rows['rate'],errors='coerce')
        rate_lookup={}
        for ch, grp in pb_rule_rows.groupby('channel_norm') if not pb_rule_rows.empty else []:
            confirmed=grp[grp.get('rule_status',pd.Series('',index=grp.index)).astype(str).str.upper().eq('CONFIRMED')] if 'rule_status' in grp.columns else grp
            if len(confirmed)==1 and pd.notna(confirmed.iloc[0].get('rate_num')):
                rate_lookup[ch]=(float(confirmed.iloc[0]['rate_num']),str(confirmed.iloc[0]['rule_id']))
            else:
                rate_lookup[ch]=None
        pb_rows['master_rate']=pb_rows['population'].map(lambda x: rate_lookup.get(x,(None,None))[0] if rate_lookup.get(x) else pd.NA)
        pb_rows['commission_rule_id']=pb_rows['population'].map(lambda x: rate_lookup.get(x,(None,None))[1] if rate_lookup.get(x) else pd.NA)
        pb_rows['rate_source']=pb_rows['master_rate'].map(lambda v: 'APPROVED_GEOGRAPHY_MASTER' if pd.notna(v) else '')
        # When the uploaded BC commission sheet has no usable rural/urban population
        # for a CSP, recover the rate only if its paid unit amount exactly matches one
        # of the permanent confirmed SBI rates. This uses the approved master as an
        # allow-list (₹5/₹6), never accepts arbitrary rates, and marks the result
        # provisional because the payout-derived rate is not independent geography proof.
        paid_pb = cm_geo.copy()
        paid_pb['csp_id'] = map_unique(paid_pb['csp_id'], norm)
        paid_pb['transaction_type'] = map_unique(paid_pb['transaction_type'], norm)
        paid_pb = paid_pb[paid_pb['transaction_type'].eq('PASSBOOK PRINTING')].copy()
        if not paid_pb.empty:
            paid_pb['report_base'] = pd.to_numeric(paid_pb.get('report_base'), errors='coerce')
            paid_pb['actual_commission'] = pd.to_numeric(paid_pb.get('actual_commission'), errors='coerce')
            paid_pb = paid_pb.groupby('csp_id', as_index=False).agg(
                _bc_count=('report_base', lambda v: v.sum(min_count=1)),
                _bc_paid=('actual_commission', lambda v: v.sum(min_count=1)),
            )
            paid_lookup = {norm(r['csp_id']): (r['_bc_count'], r['_bc_paid']) for _, r in paid_pb.iterrows()}
            approved_values = sorted({float(v[0]) for v in rate_lookup.values() if v and v[0] is not None})
            def _fallback_rate(csp, population):
                if norm(population) == 'CONFLICT':
                    return None
                vals = paid_lookup.get(norm(csp))
                if not vals or pd.isna(vals[0]) or float(vals[0]) <= 0 or pd.isna(vals[1]):
                    return None
                implied = float(vals[1]) / float(vals[0])
                matches = [v for v in approved_values if abs(implied - v) < 0.0001]
                return matches[0] if len(matches) == 1 else None
            missing_rate = pd.to_numeric(pb_rows['master_rate'], errors='coerce').isna()
            for _idx in pb_rows.index[missing_rate]:
                fallback = _fallback_rate(pb_rows.at[_idx, 'csp_id'], pb_rows.at[_idx, 'population'])
                if fallback is not None:
                    pb_rows.at[_idx, 'master_rate'] = fallback
                    pb_rows.at[_idx, 'rate_source'] = 'BC_PAID_UNIT_RATE_MATCHES_APPROVED_SBI_RATE_PROVISIONAL'
        pb_rows['source_rate_mismatch']=pd.to_numeric(pb_rows['rate'],errors='coerce').notna() & pd.to_numeric(pb_rows['master_rate'],errors='coerce').notna() & (pd.to_numeric(pb_rows['rate'],errors='coerce')-pd.to_numeric(pb_rows['master_rate'],errors='coerce')).abs().gt(0.005)
        pb_rows['expected_commission']=pb_rows['count'] * pd.to_numeric(pb_rows['master_rate'],errors='coerce')

        # Collapse the period-level calculation to one CSP row only after each period's
        # applicable approved rate has been applied. Otherwise joining one BC monthly
        # total to several period rows would duplicate actual commission and counts.
        if 'period' in pb_rows.columns and pb_rows['period'].map(_period_month).nunique() > 1:
            def _one_area(values):
                vals = {norm(v) for v in values if norm(v)}
                return next(iter(vals)) if len(vals) == 1 else ('CONFLICT' if vals else '')
            pb_rows = pb_rows.groupby('csp_id', as_index=False, dropna=False).agg(
                transaction_type=('transaction_type', 'first'),
                join_type=('join_type', 'first'), bc_join_type=('bc_join_type', 'first'),
                count=('count', 'sum'), population=('population', _one_area),
                rate=('rate', 'first'), master_rate=('master_rate', 'first'),
                commission_rule_id=('commission_rule_id', 'first'), rate_source=('rate_source', 'first'),
                expected_commission=('expected_commission', lambda x: pd.to_numeric(x, errors='coerce').sum(min_count=1)),
                successful_transactions=('successful_transactions', 'sum'),
                source_rate_mismatch=('source_rate_mismatch', 'max'),
                period=('period', lambda x: ','.join(sorted({_period_month(v) for v in x if _period_month(v)})))
            )

        # IMPORTANT CONTROL: actual Passbook population and paid commission come from
        # the normalized BC commission report supplied to the project, not from the
        # derived reconciliation workbook. The workbook is retained only as a
        # secondary validation/control artifact. This prevents circular reconciliation.
        cm_pb=commission.copy()
        cm_pb['csp_id']=map_unique(cm_pb['csp_id'], norm)
        cm_pb['transaction_type']=map_unique(cm_pb['transaction_type'], norm)
        cm_pb=cm_pb[cm_pb['transaction_type'].eq('PASSBOOK PRINTING')].copy()
        if not cm_pb.empty:
            cm_pb['report_base']=pd.to_numeric(cm_pb['report_base'],errors='coerce')
            cm_pb['actual_commission']=pd.to_numeric(cm_pb['actual_commission'],errors='coerce')
            cm_pb=cm_pb.groupby('csp_id',as_index=False).agg(report_base=('report_base','sum'),actual_commission=('actual_commission','sum'))
        pb_rows=pb_rows.merge(cm_pb,on='csp_id',how='left',suffixes=('','_bc'))
        # Recompute the control differences from the independently sourced BC report.
        pb_rows['passbook_count_difference']=pd.to_numeric(pb_rows['count'],errors='coerce')-pd.to_numeric(pb_rows['report_base'],errors='coerce')
        pb_rows['passbook_revenue_difference']=pd.to_numeric(pb_rows['actual_commission'],errors='coerce')-pd.to_numeric(pb_rows['expected_commission'],errors='coerce')

        # Compare the independently sourced result with the user-supplied reconciliation
        # workbook, if present. Any disagreement is an explicit control exception; the
        # derived workbook is never used to overwrite the project result.
        pb_recon=load_passbook_printing_reconciliation(transaction_month)
        if not pb_recon.empty:
            ctl=pb_recon[['csp_id','source_count','bank_count','actual_commission','expected_commission']].copy()
            ctl=ctl.rename(columns={'source_count':'ctl_source_count','bank_count':'ctl_bank_count','actual_commission':'ctl_actual_commission','expected_commission':'ctl_expected_commission'})
            pb_rows=pb_rows.merge(ctl,on='csp_id',how='left')
            pb_rows['passbook_control_validation_status']=pd.Series('NO_CONTROL_ROW',index=pb_rows.index,dtype='string')
            same=(pd.to_numeric(pb_rows['count'],errors='coerce').eq(pd.to_numeric(pb_rows['ctl_source_count'],errors='coerce')) &
                  pd.to_numeric(pb_rows['report_base'],errors='coerce').eq(pd.to_numeric(pb_rows['ctl_bank_count'],errors='coerce')) &
                  (pd.to_numeric(pb_rows['actual_commission'],errors='coerce')-pd.to_numeric(pb_rows['ctl_actual_commission'],errors='coerce')).abs().le(0.005) &
                  (pd.to_numeric(pb_rows['expected_commission'],errors='coerce')-pd.to_numeric(pb_rows['ctl_expected_commission'],errors='coerce')).abs().le(0.005))
            pb_rows.loc[same,'passbook_control_validation_status']='MATCH'
            pb_rows.loc[~same & pb_rows['ctl_source_count'].notna(),'passbook_control_validation_status']='CONTROL_MISMATCH'
        else:
            pb_rows['passbook_control_validation_status']='CONTROL_NOT_AVAILABLE'

        # The CSP-wise source has no account IDs, so the SBI 5-print/account/month cap
        # cannot be independently verified. Keep the uncapped rule result as provisional,
        # but do not treat it as settlement-approved expected revenue.
        pb_rows['verified_expected_commission']=pd.NA
        pb_rows['expected_commission_low']=pb_rows['expected_commission']
        pb_rows['expected_commission_high']=pb_rows['expected_commission']
        pb_rows['geography_unresolved_transactions']=pb_rows['master_rate'].isna().astype(int)*pb_rows['successful_transactions']
        pb_rows['rate_rule_missing']=pb_rows['master_rate'].isna().astype(int)*pb_rows['successful_transactions']
        pb_rows['rate_rule_ambiguous']=0
        pb_rows['rate_rule_applied']=pb_rows['master_rate'].notna().astype(int)*pb_rows['successful_transactions']
        pb_rows['rate_rule_pending']=0
        pb_rows['rate_rule_geography_resolved']=pb_rows['rate_rule_applied']
        pb_rows['condition_fail_transactions']=0
        pb_rows['required_evidence_transactions']=pb_rows['successful_transactions']
        pb_rows['expected_transaction_rows']=pb_rows['expected_commission'].notna().astype(int)*pb_rows['successful_transactions']
        pb_rows['is_supplemental']=True
        pb_rows['passbook_cap_status']='NOT_VERIFIABLE_ACCOUNT_LEVEL_SOURCE'
        pb_add=pb_rows.drop(columns=['count','population','rate','period'])
        if 'passbook_cap_status' not in txg.columns:
            txg['passbook_cap_status']=pd.NA
        if 'passbook_count_difference' not in txg.columns:
            txg['passbook_count_difference']=pd.NA
        if 'passbook_revenue_difference' not in txg.columns:
            txg['passbook_revenue_difference']=pd.NA
        if 'passbook_control_validation_status' not in txg.columns:
            txg['passbook_control_validation_status']=pd.NA
        for _col in txg.columns:
            if _col not in pb_add.columns:
                pb_add[_col]=pd.NA
        pb_add=pb_add[txg.columns]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FutureWarning)
            txg=pd.concat([txg,pb_add],ignore_index=True,sort=False)

    unm=tx[tx['join_type'].isna()].groupby(['csp_id','transaction_type'],dropna=False).agg(
        successful_transactions=('successful_transactions','sum'),transaction_amount=('transaction_amount','sum')
    ).reset_index()
    if not unm.empty:
        unm['join_type']=pd.NA; unm['mapping_confidence']='UNMAPPED'; unm['expected_commission']=pd.NA; unm['verified_expected_commission']=pd.NA; unm['expected_commission_low']=pd.NA; unm['expected_commission_high']=pd.NA; unm['geography_unresolved_transactions']=0; unm['commission_rule_id']=pd.NA
        unm['rate_rule_missing']=unm['successful_transactions']; unm['rate_rule_ambiguous']=0; unm['rate_rule_applied']=0; unm['rate_rule_pending']=0; unm['condition_fail_transactions']=0; unm['required_evidence_transactions']=0; unm['expected_transaction_rows']=0
        unm['actual_commission']=pd.NA; unm['report_base']=pd.NA; unm['commission_report_rows']=0
        unm['count_variance']=pd.NA; unm['financial_gap']=pd.NA; unm['variance']=pd.NA
        unm['financial_gap_status']='Not Comparable'; unm['reconciliation_status']='UNMAPPED'; unm['investigation_status']='UNMAPPED'; unm['mismatch_reason']='No exact approved transaction-type mapping'; unm['mismatch_priority']='HIGH'; unm['exception_flag']=True
        unm['amount']=unm['transaction_amount']; unm['transaction_id']=pd.NA

    cm=commission.copy()
    cm['csp_id']=map_unique(cm['csp_id'], norm); cm['transaction_type']=map_unique(cm['transaction_type'], norm)
    # Normalize the BC report through the SAME canonical transaction mapping used
    # for successful transactions. The BC report is an aggregated CSP/type report,
    # so labels such as WITHDRAWAL vs CASH WITHDRAWAL and ATM ONUS WITHDRAWAL vs
    # DEBIT CARD ONUS must resolve to the same commercial key before joining.
    # Resolution depends only on the label here, so resolve each distinct label once.
    bc_types=cm['transaction_type'].unique()
    bc_join_lookup={t:(resolve_transaction_type(t,None,ref_map) or t) for t in bc_types}
    bc_join_lookup.update({t:t for t in bc_types if t in BC_OWN_LINE_TYPES})
    cm['bc_join_type']=cm['transaction_type'].map(bc_join_lookup)
    cm['actual_commission']=parse_numeric_series(cm['actual_commission'])
    cm['report_base']=parse_numeric_series(cm['report_base']) if 'report_base' in cm else pd.Series(pd.NA,index=cm.index,dtype='Float64')
    cm['measurement_type']=cm['transaction_type'].map({t:classify_bc_measurement_type(t) for t in bc_types})
    # Keep every valid BC commission category. Unrecognized categories become
    # explicit BC-only activity instead of being silently discarded.
    cm=cm[cm['csp_id'].ne('') & cm['transaction_type'].ne('') & cm['actual_commission'].notna()].copy()
    cmg=_group_aggregate(cm,['csp_id','bc_join_type'],[
        ('actual_commission','actual_commission','sum'),
        ('commission_report_rows','actual_commission','size'),
        ('report_base','report_base','sum_min1'),
        ('measurement_type','measurement_type','first'),
    ])

    r=txg.merge(cmg,left_on=['csp_id','bc_join_type'],right_on=['csp_id','bc_join_type'],how='outer',indicator=True,suffixes=('','_bc'))
    r['successful_transactions']=r['successful_transactions'].fillna(0).astype(int)
    r['transaction_amount']=pd.to_numeric(r['transaction_amount'],errors='coerce').fillna(0)
    r['expected_commission']=pd.to_numeric(r['expected_commission'],errors='coerce')
    r['expected_commission_low']=pd.to_numeric(r.get('expected_commission_low'),errors='coerce')
    r['expected_commission_high']=pd.to_numeric(r.get('expected_commission_high'),errors='coerce')
    r['actual_commission']=pd.to_numeric(r['actual_commission'],errors='coerce')
    r['report_base']=pd.to_numeric(r['report_base'],errors='coerce')
    r['commission_report_rows']=r['commission_report_rows'].fillna(0).astype(int)
    r['measurement_type']=r.get('measurement_type',pd.Series(pd.NA,index=r.index)).fillna('UNCLASSIFIED')
    r['is_supplemental']=r.get('is_supplemental',pd.Series(False,index=r.index,dtype=bool)).astype('boolean').fillna(False).astype(bool)
    r['count_variance']=pd.NA
    # Only a BC row explicitly classified as transaction-count activity can be
    # compared with successful transaction rows. Average-balance/incentive/penalty
    # values are never interpreted as transaction counts.
    has_base=(r['measurement_type'].eq('TRANSACTION_COUNT') & r['report_base'].notna() & r['successful_transactions'].gt(0))
    r.loc[has_base,'count_variance']=r.loc[has_base,'successful_transactions']-r.loc[has_base,'report_base']
    r['count_match_status']=pd.NA
    r.loc[has_base & r['count_variance'].abs().le(1e-9),'count_match_status']='MATCH'
    r.loc[has_base & r['count_variance'].abs().gt(1e-9),'count_match_status']='SOURCE_COUNT_DIFFERENCE'
    r.loc[~has_base & r['successful_transactions'].gt(0),'count_match_status']='NOT_COUNT_COMPARABLE'
    r['difference_pct']=pd.NA
    pctmask=has_base & r['report_base'].ne(0)
    r.loc[pctmask,'difference_pct']=(r.loc[pctmask,'count_variance'].abs()/r.loc[pctmask,'report_base'].abs()*100)
    r.loc[has_base & r['report_base'].eq(0) & r['successful_transactions'].gt(0),'difference_pct']=pd.NA
    if 'transaction_type_bc' in r.columns:
        r['transaction_type']=r['transaction_type'].fillna(r['transaction_type_bc'])
        r=r.drop(columns=['transaction_type_bc'])
    if 'bc_join_type' in r.columns:
        r['join_type']=r['join_type'].fillna(r['bc_join_type'])
        r=r.drop(columns=['bc_join_type'])

    # Monetary comparison is deliberately restricted to transaction activity for
    # which EVERY successful transaction in the CSP+type group has exactly one
    # approved rule. A partially covered group must never have its partial expected
    # amount compared with the full BC commission, because that would manufacture a
    # false financial gap.
    r['rate_rule_complete'] = (
        r['successful_transactions'].gt(0)
        & r['rate_rule_missing'].fillna(0).eq(0)
        & r['rate_rule_ambiguous'].fillna(0).eq(0)
        & r['rate_rule_applied'].fillna(0).eq(r['successful_transactions'])
    )
    # A calculated rule can still be commercially pending when the SBI workbook
    # says "Mapping to confirm". Such rows are useful for control/diagnostics, but
    # they must not be treated as final settlement figures.
    r['settlement_rule_approved'] = (
        r['rate_rule_complete']
        & pd.to_numeric(r['rate_rule_pending'],errors='coerce').fillna(0).eq(0)
        & pd.to_numeric(r['required_evidence_transactions'],errors='coerce').fillna(0).eq(0)
    )
    r['actual_comparable_commission']=pd.NA
    # A missing BC commission row is NOT zero actual revenue. Only compare money
    # when both expected and actual populations are present. This prevents an
    # unmapped/missing BC population from becoming a synthetic shortfall.
    comparable=r['settlement_rule_approved'] & r['expected_commission'].notna() & r['actual_commission'].notna()
    r.loc[comparable,'actual_comparable_commission']=r.loc[comparable,'actual_commission']
    r['financial_gap']=pd.NA
    r.loc[comparable,'financial_gap']=r.loc[comparable,'expected_commission']-r.loc[comparable,'actual_comparable_commission']
    r.loc[r['rate_rule_pending'].fillna(0).gt(0) & r['expected_commission'].notna(),'financial_gap_status']='Provisional - Mapping Pending'
    # Provisional transaction-financial comparison: when a deterministic expected
    # amount exists and the BC group has actual commission, compare those two
    # populations even if the SBI master marks the product mapping as
    # "Mapping to confirm". This is an analytical control only; it never replaces
    # the settlement-approved `financial_gap` above.
    provisional = (
        r['successful_transactions'].gt(0)
        & r['expected_commission'].notna()
        & r['actual_commission'].notna()
    )
    r['provisional_actual_commission'] = pd.NA
    r.loc[provisional, 'provisional_actual_commission'] = r.loc[provisional, 'actual_commission']
    r['provisional_financial_gap'] = pd.NA
    r.loc[provisional, 'provisional_financial_gap'] = (
        r.loc[provisional, 'expected_commission'] -
        r.loc[provisional, 'provisional_actual_commission']
    )
    r['provisional_financial_gap_status'] = 'Not Comparable'
    r.loc[provisional & r['provisional_financial_gap'].abs().le(0.005), 'provisional_financial_gap_status'] = 'Matched'
    r.loc[provisional & r['provisional_financial_gap'].gt(0.005), 'provisional_financial_gap_status'] = 'Shortfall'
    r.loc[provisional & r['provisional_financial_gap'].lt(-0.005), 'provisional_financial_gap_status'] = 'Excess'
    r.loc[
        provisional & r['rate_rule_pending'].fillna(0).gt(0),
        'provisional_financial_gap_status'
    ] = 'Provisional - Mapping Pending'

    r['variance']=r['financial_gap']
    r['financial_gap_status']='Not Comparable'
    r.loc[comparable & r['financial_gap'].abs().le(0.005),'financial_gap_status']='Matched'
    r.loc[comparable & r['financial_gap'].gt(0.005),'financial_gap_status']='Shortfall'
    r.loc[comparable & r['financial_gap'].lt(-0.005),'financial_gap_status']='Excess'

    # Vectorized status classification: avoids Python row callbacks on large
    # CSP x transaction-type reconciliation populations while preserving precedence.
    merge = r.get('_merge', pd.Series('both', index=r.index)).astype('string')
    measurement = r.get('measurement_type', pd.Series('', index=r.index)).astype('string')
    count_status = r.get('count_match_status', pd.Series('', index=r.index)).astype('string')
    ambiguous = pd.to_numeric(r.get('rate_rule_ambiguous', 0), errors='coerce')
    if not isinstance(ambiguous, pd.Series): ambiguous = pd.Series(ambiguous, index=r.index)
    ambiguous = ambiguous.fillna(0).gt(0)
    condition_fail = pd.to_numeric(r.get('condition_fail_transactions', 0), errors='coerce')
    if not isinstance(condition_fail, pd.Series): condition_fail = pd.Series(condition_fail, index=r.index)
    condition_fail = condition_fail.fillna(0).gt(0)
    rate_missing = pd.to_numeric(r.get('rate_rule_missing', 0), errors='coerce')
    if not isinstance(rate_missing, pd.Series): rate_missing = pd.Series(rate_missing, index=r.index)
    rate_missing = rate_missing.fillna(0).gt(0)
    evidence = pd.to_numeric(r.get('required_evidence_transactions', 0), errors='coerce')
    if not isinstance(evidence, pd.Series): evidence = pd.Series(evidence, index=r.index)
    evidence = evidence.fillna(0).gt(0)
    pending = pd.to_numeric(r.get('rate_rule_pending', 0), errors='coerce')
    if not isinstance(pending, pd.Series): pending = pd.Series(pending, index=r.index)
    pending = pending.fillna(0).gt(0)
    complete = r.get('rate_rule_complete', pd.Series(False, index=r.index)).fillna(False).astype(bool)
    expected_missing = r.get('expected_commission', pd.Series(pd.NA, index=r.index)).isna()
    conditions = [
        merge.eq('right_only') & measurement.ne('TRANSACTION_COUNT'),
        merge.eq('right_only'),
        merge.eq('left_only') & r.get('join_type', pd.Series(pd.NA, index=r.index)).isna(),
        merge.eq('left_only'),
        count_status.eq('SOURCE_COUNT_DIFFERENCE'),
        ambiguous,
        condition_fail & ~rate_missing,
        evidence & ~rate_missing,
        rate_missing | ~complete | expected_missing,
        pending,
        r.get('financial_gap_status', pd.Series('', index=r.index)).isin(['Shortfall','Excess']),
    ]
    choices = ['BC_ONLY_ACTIVITY','SOURCE_COUNT_DIFFERENCE','UNMAPPED','SOURCE_COUNT_DIFFERENCE',
               'SOURCE_COUNT_DIFFERENCE','AMBIGUOUS_RATE_RULE','CONDITION_FAIL','EVIDENCE_REQUIRED',
               'RATE_MASTER_MISSING','MAPPING_PENDING',r.get('financial_gap_status', pd.Series('MATCH', index=r.index))]
    # pandas nullable StringDtype comparisons may yield BooleanArray values
    # containing pd.NA; numpy.select requires strict boolean ndarrays. Normalize
    # every condition to a non-null bool ndarray before classification.
    safe_conditions = [
        pd.Series(condition, index=r.index).fillna(False).astype(bool).to_numpy(dtype=bool)
        if not isinstance(condition, pd.Series)
        else condition.fillna(False).astype(bool).to_numpy(dtype=bool)
        for condition in conditions
    ]
    # Keep the final per-row financial status choice aligned to the result index.
    safe_choices = list(choices)
    safe_choices[-1] = (
        r.get('financial_gap_status', pd.Series('MATCH', index=r.index))
        .fillna('MATCH').astype(str).to_numpy()
    )
    r['reconciliation_status'] = np.select(safe_conditions, safe_choices, default='MATCH')
    r['exception_flag']=(r['reconciliation_status']!='MATCH') | r['financial_gap_status'].isin(['Shortfall','Excess'])
    r['investigation_status']=r['reconciliation_status'].map({
        'MATCH':'MATCH','SOURCE_COUNT_DIFFERENCE':'INVESTIGATE','BC_ONLY_ACTIVITY':'INVESTIGATE',
        'UNMAPPED':'UNMAPPED','RATE_MASTER_MISSING':'INVESTIGATE','AMBIGUOUS_RATE_RULE':'INVESTIGATE',
        'MAPPING_PENDING':'INVESTIGATE','CONDITION_FAIL':'INVESTIGATE','EVIDENCE_REQUIRED':'INVESTIGATE','Shortfall':'INVESTIGATE','Excess':'INVESTIGATE'
    }).fillna('INVESTIGATE')
    # Vectorized mismatch explanations; avoid per-row Python callbacks.
    status = r['reconciliation_status'].astype('string')
    cms = r.get('count_match_status', pd.Series('', index=r.index)).astype('string')
    cv = pd.to_numeric(r.get('count_variance', pd.Series(0, index=r.index)), errors='coerce').fillna(0)
    reason_conditions = [
        status.eq('UNMAPPED'),
        cms.eq('SOURCE_COUNT_DIFFERENCE') & cv.gt(0),
        cms.eq('SOURCE_COUNT_DIFFERENCE') & cv.lt(0),
        status.eq('BC_ONLY_ACTIVITY'),
        status.eq('RATE_MASTER_MISSING'),
        status.eq('CONDITION_FAIL'),
        status.eq('EVIDENCE_REQUIRED'),
        status.eq('MAPPING_PENDING'),
        status.eq('AMBIGUOUS_RATE_RULE'),
        status.eq('Shortfall'),
        status.eq('Excess'),
    ]
    r['mismatch_reason'] = np.select(reason_conditions, [
        'No exact approved transaction-type mapping',
        'BC count lower than successful source',
        'BC count higher than successful source',
        'BC-only activity; verify incentive/non-transaction category or source population',
        'Approved commercial rule missing or incomplete',
        'Transaction does not satisfy the applicable SBI amount/date condition',
        'Required KYC/geography/product evidence is missing',
        'Commercial mapping/rule approval pending',
        'Ambiguous commercial rule',
        'Commission shortfall',
        'Commission excess',
    ], default='—')
    abs_variance = pd.to_numeric(r['count_variance'], errors='coerce').abs()
    r['mismatch_priority'] = np.select(
        [abs_variance.notna() & abs_variance.le(2), abs_variance.notna() & abs_variance.le(10), abs_variance.notna()],
        ['LOW','MEDIUM','HIGH'], default='N/A')
    r['amount']=r['transaction_amount']; r['transaction_id']=pd.NA
    r=r.drop(columns=['_merge'],errors='ignore')
    if not unm.empty:
        for c in r.columns:
            if c not in unm.columns: unm[c]=pd.NA
        unm=unm[r.columns]
        if not r.empty:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', FutureWarning)
                r=pd.concat([r,unm],ignore_index=True)
        else:
            r=unm.copy()
    return r

def aggregate_by_csp(r):
    x=r[r.successful_transactions>0].copy()
    return x.groupby('csp_id',dropna=False).agg(
        successful_transactions=('successful_transactions','sum'),
        transaction_amount=('transaction_amount','sum'),
        expected_commission=('expected_commission',lambda x: x.sum(min_count=1)),
        verified_expected_commission=('verified_expected_commission',lambda x: x.sum(min_count=1)),
        actual_commission=('actual_comparable_commission',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
        actual_transaction_activity_commission=('actual_commission',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
        financial_gap=('financial_gap',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
        variance=('financial_gap',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
        report_base=('report_base',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
        count_variance=('count_variance',lambda x: pd.to_numeric(x,errors='coerce').sum(min_count=1)),
        exception_groups=('exception_flag','sum')
    ).reset_index()

def _bc_to_success_display_type(bc_type, social_security_active=False):
    """Map a BC-report commercial type back to the Success-file display type.

    This is a reporting bridge only. It does not create a transaction-level match.
    Multiple BC commercial rows can legitimately belong to one Success-file type:
    the four account-opening slabs -> INITIAL DEPOSIT. PMJJBY/PMSBY remain BC-only because the
    August mapping source explicitly marks Customer enroll for SSS as having no BC equivalent.
    """
    t=norm(bc_type)
    if not t:
        return None
    # PMJJBY/PMSBY have an explicit CSP-wise August supplemental success source.
    # Keep their BC rows visible in the transaction-type control so BC-only CSPs
    # remain auditable instead of disappearing from the summary.
    if t in {"PMSBY", "PMJJBY"}:
        return t if social_security_active else None
    if t == "ADDITIONAL INCENTIVE ON AEPS CASH TRANSACTIONS":
        return t
    if t in set(ACCOUNT_OPEN_TYPES.values()):
        return "INITIAL DEPOSIT"
    reverse={v:k for k,v in TYPE_MAPPING.items()}
    return reverse.get(t)


def aggregate_by_transaction_type(r):
    """Aggregate the transaction reconciliation view by Success transaction type.

    Important source-control rule: the BC Report Base and BC Reported Commission
    shown here come from the COMPLETE uploaded BC transaction-commission sheet,
    including BC-only CSPs. They are not limited to CSPs that happened to have a
    successful-source row. Overlap/BC-only amounts are exposed separately so a
    full BC total is never mistaken for an apples-to-apples settlement comparison.
    """
    x=r.copy()
    x['successful_transactions']=pd.to_numeric(x['successful_transactions'],errors='coerce').fillna(0)
    x['report_base']=pd.to_numeric(x.get('report_base'),errors='coerce')
    x['actual_commission']=pd.to_numeric(x.get('actual_commission'),errors='coerce')

    # The canonical display type is the Success-file type. For BC-only rows the
    # original Success type is absent, so use the deterministic reverse bridge.
    x['display_transaction_type']=map_unique(x['transaction_type'], norm)
    social_security_active = bool(x.get('is_supplemental', pd.Series(False, index=x.index, dtype=bool)).astype('boolean').fillna(False).any())
    right=x['display_transaction_type'].eq('') | x['display_transaction_type'].isna()
    x.loc[right,'display_transaction_type']=x.loc[right,'join_type'].map(lambda v: _bc_to_success_display_type(v, social_security_active))

    # Only operational BC categories that map to a Success transaction type are
    # included in this table. Incentives, average-balance and penalties remain in
    # the dedicated BC workbook controls.
    x=x[x['display_transaction_type'].notna() & x['display_transaction_type'].ne('')].copy()

    success_keys=set(zip(
        x.loc[x['successful_transactions'].gt(0),'csp_id'].map(norm),
        x.loc[x['successful_transactions'].gt(0),'display_transaction_type'].map(norm)
    ))
    x['bc_row_present']=x['report_base'].notna() | x['actual_commission'].notna()
    row_keys=zip(map_unique(x['csp_id'], norm),map_unique(x['display_transaction_type'], norm))
    x['bc_overlap']=[bool(present) and key in success_keys for present,key in zip(x['bc_row_present'],row_keys)]

    def _sum(s):
        return pd.to_numeric(s,errors='coerce').sum(min_count=1)

    # Successful/expected values are intentionally calculated only from the
    # Success population. BC totals are calculated from the entire BC source.
    rows=[]
    for typ,g in x.groupby('display_transaction_type',dropna=False):
        success=g[g['successful_transactions'].gt(0)]
        bc=g[g['bc_row_present']]
        overlap=bc[bc['bc_overlap']]
        bc_only=bc[~bc['bc_overlap']]
        mapping_values=set(success.get('mapping_confidence',pd.Series(dtype=object)).dropna().astype(str).str.upper())
        mapping_conf = 'EXACT' if mapping_values == {'EXACT'} else ('PROBABLE' if 'PROBABLE' in mapping_values else ('CONDITIONAL' if 'CONDITIONAL' in mapping_values else ('UNMAPPED' if not success.empty else 'BC_ONLY')))
        applied_n=int(pd.to_numeric(success.get('rate_rule_applied',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0
        pending_n=int(pd.to_numeric(success.get('rate_rule_pending',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0
        missing_n=int(pd.to_numeric(success.get('rate_rule_missing',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0
        fail_n=int(pd.to_numeric(success.get('condition_fail_transactions',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0
        evidence_n=int(pd.to_numeric(success.get('required_evidence_transactions',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0
        expected_n=int(pd.to_numeric(success.get('expected_transaction_rows',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0
        total_n=int(success['successful_transactions'].sum())
        if total_n == 0:
            calc_status='BC_ONLY'
        elif expected_n == total_n and pending_n == 0 and mapping_conf == 'EXACT':
            calc_status='CALCULATED'
        elif expected_n == total_n and pending_n == 0 and mapping_conf == 'PROBABLE':
            calc_status='PROVISIONAL - PROBABLE MAPPING'
        elif expected_n == total_n and pending_n == 0 and mapping_conf == 'CONDITIONAL':
            calc_status='CALCULATED - MAPPING CONDITIONAL'
        elif expected_n > 0 and pending_n > 0:
            calc_status='PROVISIONAL - MAPPING PENDING'
        elif evidence_n > 0:
            calc_status='CONDITIONAL - EVIDENCE REQUIRED'
        elif fail_n > 0:
            calc_status='PARTIAL - CONDITION FAIL'
        elif missing_n > 0:
            calc_status='UNRESOLVED - RULE MISSING'
        else:
            calc_status='PARTIAL'
        rows.append({
            'transaction_type': typ,
            'mapping_confidence': mapping_conf,
            'expected_calculation_status': calc_status,
            'successful_transactions': total_n,
            'transaction_amount': float(_sum(success['transaction_amount']) or 0),
            'expected_commission': _sum(success['expected_commission']),
            'verified_expected_commission': _sum(success['verified_expected_commission']),
            'actual_commission': _sum(overlap['actual_commission']),
            'actual_transaction_activity_commission': _sum(bc['actual_commission']),
            'financial_gap': _sum(success['financial_gap']),
            'variance': _sum(success['financial_gap']),
            # `report_base` is the comparable BC count for this transaction type;
            # the complete BC-source total remains available separately.
            'report_base': _sum(overlap['report_base']),
            'bc_report_base_total': _sum(bc['report_base']),
            'bc_report_commission_total': _sum(bc['actual_commission']),
            'bc_report_base_overlap': _sum(overlap['report_base']),
            'bc_report_commission_overlap': _sum(overlap['actual_commission']),
            'bc_only_base': _sum(bc_only['report_base']),
            'bc_only_commission': _sum(bc_only['actual_commission']),
            # Count reconciliation must use only the BC population that overlaps
            # the Success CSP + transaction-type population. BC-only CSPs/categories
            # are reported separately and must not inflate the denominator/difference.
            'count_variance': (int(success['successful_transactions'].sum()) - float(_sum(overlap['report_base']))) if pd.notna(_sum(overlap['report_base'])) else None,
            'bc_overlap_csp_count': int(overlap['csp_id'].nunique()),
            'bc_only_csp_count': int(bc_only['csp_id'].nunique()),
            'rate_rule_applied_transactions': int(pd.to_numeric(success.get('rate_rule_applied',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0,
            'rate_rule_pending_transactions': int(pd.to_numeric(success.get('rate_rule_pending',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0,
            'rate_rule_missing_transactions': int(pd.to_numeric(success.get('rate_rule_missing',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0,
            'condition_fail_transactions': int(pd.to_numeric(success.get('condition_fail_transactions',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0,
            'expected_transaction_rows': int(pd.to_numeric(success.get('expected_transaction_rows',pd.Series(dtype=float)),errors='coerce').sum()) if not success.empty else 0,
            'exception_groups': int(success['exception_flag'].sum()) if 'exception_flag' in success else 0,
            'passbook_cap_status': ('NOT_VERIFIABLE_ACCOUNT_LEVEL_SOURCE' if typ == 'PASSBOOK PRINTING' and not success.empty else None),
            'passbook_count_difference': _sum(success.get('passbook_count_difference',pd.Series(dtype=float))) if typ == 'PASSBOOK PRINTING' else None,
            'passbook_revenue_difference_bank_minus_expected': _sum(success.get('passbook_revenue_difference',pd.Series(dtype=float))) if typ == 'PASSBOOK PRINTING' else None,
            'passbook_source_csp_count': int(success['csp_id'].nunique()) if typ == 'PASSBOOK PRINTING' and not success.empty else 0,
        })
    out=pd.DataFrame(rows)
    if out.empty:
        return out
    out=out.sort_values(['successful_transactions','transaction_type'],ascending=[False,True]).reset_index(drop=True)
    return out




def reconcile_social_security_direct(source_counts, commission, period=None):
    """Independently reconcile CSP-wise PMJJBY/PMSBY counts to the uploaded BC report.

    This control intentionally does not depend on unrelated successful transaction
    dates, rate-master upload batches, or supplemental rows being injected into the
    main transaction reconciliation. Source and BC periods must be checked by caller.
    """
    if source_counts is None or source_counts.empty or commission is None or commission.empty:
        return {"available": False, "status": "SOURCE_REQUIRED", "message": "Upload PMJJBY/PMSBY source counts and the matching-period BC commission report.", "schemes": [], "rows": [], "total": {}}
    src=source_counts.copy()
    cm=commission.copy()
    for col in ["csp_id", "transaction_type"]:
        if col not in src.columns or col not in cm.columns:
            return {"available": False, "status": "INVALID_SCHEMA", "message": "Both source and BC report must contain CSP ID and transaction type/scheme.", "schemes": [], "rows": [], "total": {}}
    if "count" not in src.columns or "actual_commission" not in cm.columns:
        return {"available": False, "status": "INVALID_SCHEMA", "message": "Source must contain count; BC report must contain actual commission.", "schemes": [], "rows": [], "total": {}}
    src["csp_id"]=map_unique(src["csp_id"], norm)
    src["transaction_type"]=map_unique(src["transaction_type"], norm)
    src["count"]=pd.to_numeric(src["count"],errors="coerce")
    src=src[src["csp_id"].str.match(r"^1A85\d{4}$",na=False) & src["transaction_type"].isin(["PMJJBY","PMSBY"]) & src["count"].notna() & src["count"].gt(0)].copy()
    cm["csp_id"]=map_unique(cm["csp_id"], norm)
    cm["transaction_type"]=map_unique(cm["transaction_type"], norm)
    cm["actual_commission"]=parse_numeric_series(cm["actual_commission"])
    if "report_base" not in cm.columns:
        cm["report_base"]=pd.NA
    cm["report_base"]=parse_numeric_series(cm["report_base"])
    cm=cm[cm["csp_id"].str.match(r"^1A85\d{4}$",na=False) & cm["transaction_type"].isin(["PMJJBY","PMSBY"]) & cm["actual_commission"].notna()].copy()
    if period and "period" in src.columns:
        src=src[src["period"].map(_period_month).eq(_period_month(period))].copy()
    # Source rates are derived only from the approved monthly SBI policy.
    schemes=[]; all_rows=[]
    for scheme in ["PMJJBY","PMSBY"]:
        ss=src[src["transaction_type"].eq(scheme)].copy()
        if ss.empty: continue
        if "period" not in ss.columns:
            return {"available":False,"status":"PERIOD_REQUIRED","message":"Social-security source needs an explicit month/period.","schemes":[],"rows":[],"total":{}}
        ss["rate"]=ss["period"].map(lambda x: _pmjjby_rate_for_period(x) if scheme=="PMJJBY" else PMSBY_COMMISSION_PER_ENROLLMENT)
        if ss["rate"].isna().any():
            return {"available":False,"status":"RATE_UNRESOLVED","message":f"Approved {scheme} rate could not be resolved for every source period.","schemes":[],"rows":[],"total":{}}
        ss["expected_commission"]=ss["count"]*ss["rate"]
        ss=ss.groupby("csp_id",as_index=False).agg(source_count=("count","sum"),expected_commission=("expected_commission","sum"))
        bc=cm[cm["transaction_type"].eq(scheme)].groupby("csp_id",as_index=False).agg(bc_count=("report_base",lambda x: x.sum(min_count=1)),actual_commission=("actual_commission","sum"))
        keys=pd.DataFrame({"csp_id":sorted(set(ss.csp_id)|set(bc.csp_id))})
        x=keys.merge(ss,on="csp_id",how="left").merge(bc,on="csp_id",how="left")
        for c in ["source_count","expected_commission","bc_count","actual_commission"]: x[c]=pd.to_numeric(x[c],errors="coerce").fillna(0)
        x["count_difference"]=x["source_count"]-x["bc_count"]
        x["commission_difference_bc_minus_expected"]=x["actual_commission"]-x["expected_commission"]
        def status(z):
            if abs(z["count_difference"])<1e-9 and abs(z["commission_difference_bc_minus_expected"])<0.005: return "MATCHED"
            if z["commission_difference_bc_minus_expected"]>0.005: return "BC EXCESS"
            if z["commission_difference_bc_minus_expected"]<-0.005: return "BC SHORT"
            return "COUNT MISMATCH"
        x["status"]=x.apply(status,axis=1); x["transaction_type"]=scheme
        schemes.append({"transaction_type":scheme,"source_transactions":int(x.source_count.sum()),"bc_transactions":int(x.bc_count.sum()),"transaction_difference":int(x.bc_count.sum()-x.source_count.sum()),"expected_commission":round(float(x.expected_commission.sum()),2),"actual_commission":round(float(x.actual_commission.sum()),2),"commission_difference_bc_minus_expected":round(float(x.commission_difference_bc_minus_expected.sum()),2),"matched_csp_count":int((x.status=="MATCHED").sum()),"bc_excess_csp_count":int((x.status=="BC EXCESS").sum()),"bc_short_csp_count":int((x.status=="BC SHORT").sum()),"count_mismatch_csp_count":int((x.status=="COUNT MISMATCH").sum())})
        all_rows.extend(x[["csp_id","transaction_type","source_count","bc_count","count_difference","expected_commission","actual_commission","commission_difference_bc_minus_expected","status"]].to_dict(orient="records"))
    total={"transaction_type":"TOTAL","source_transactions":sum(x["source_transactions"] for x in schemes),"bc_transactions":sum(x["bc_transactions"] for x in schemes),"transaction_difference":sum(x["transaction_difference"] for x in schemes),"expected_commission":round(sum(x["expected_commission"] for x in schemes),2),"actual_commission":round(sum(x["actual_commission"] for x in schemes),2),"commission_difference_bc_minus_expected":round(sum(x["commission_difference_bc_minus_expected"] for x in schemes),2)}
    detail=pd.DataFrame(all_rows)
    source_key_rows=detail[pd.to_numeric(detail.get("source_count"),errors="coerce").fillna(0).gt(0)] if not detail.empty else pd.DataFrame()
    bc_only_rows=detail[pd.to_numeric(detail.get("source_count"),errors="coerce").fillna(0).eq(0) & pd.to_numeric(detail.get("actual_commission"),errors="coerce").fillna(0).gt(0)] if not detail.empty else pd.DataFrame()
    matched_key_summary={"source_transactions":int(pd.to_numeric(source_key_rows.get("source_count",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),"bc_transactions":int(pd.to_numeric(source_key_rows.get("bc_count",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),"expected_commission":round(float(pd.to_numeric(source_key_rows.get("expected_commission",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),2),"actual_commission":round(float(pd.to_numeric(source_key_rows.get("actual_commission",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),2),"commission_difference_bc_minus_expected":round(float(pd.to_numeric(source_key_rows.get("commission_difference_bc_minus_expected",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),2)}
    bc_only_summary={"csp_scheme_groups":int(len(bc_only_rows)),"bc_transactions":int(pd.to_numeric(bc_only_rows.get("bc_count",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),"actual_commission":round(float(pd.to_numeric(bc_only_rows.get("actual_commission",pd.Series(dtype=float)),errors="coerce").fillna(0).sum()),2)}
    return {"available":bool(schemes),"status":"READY" if schemes else "NO_MATCHING_SCHEMES","period":period,"schemes":schemes,"total":total,"matched_source_keys":matched_key_summary,"bc_only":bc_only_summary,"rows":all_rows,"matching_basis":"Exact CSP ID + scheme; aggregate counts and actual commission; no fuzzy CSP matching."}


def aggregate_social_security_reconciliation(r, transaction_month=None, transaction_months=None, infer_single_source_period=True):
    """Reconcile PMJJBY/PMSBY source counts against BC actuals for the run periods.

    Rates are calculated row-by-row for each source period before aggregation, so a
    multi-month upload never applies August's rate to September or duplicates one BC
    payout across several monthly source rows.
    """
    ss=load_social_security_counts()
    allowed=set(transaction_months or ([] if transaction_month is None else [transaction_month]))
    active_period=transaction_month if transaction_month else (next(iter(allowed)) if len(allowed)==1 else None)
    if allowed and not ss.empty:
        ss=ss[ss['period'].map(_period_month).isin(allowed)].copy()
    elif infer_single_source_period and not ss.empty:
        periods=ss['period'].map(_period_month).dropna().unique().tolist()
        active_period=periods[0] if len(periods)==1 else None
        ss=ss[ss['period'].map(_period_month).eq(active_period)].copy() if active_period else ss.iloc[0:0].copy()
    else:
        ss=ss.iloc[0:0].copy()
    supplemental_mask=r.get('is_supplemental',pd.Series(False,index=r.index)).astype('boolean').fillna(False).astype(bool)
    scheme_mask=r.get('transaction_type',pd.Series('',index=r.index)).astype('string').isin(['PMJJBY','PMSBY'])
    source_quality=load_social_security_count_exceptions(transaction_month=active_period, transaction_months=transaction_months)
    if ss.empty or not (supplemental_mask & scheme_mask).any():
        return {'available':False,'schemes':[],'rows':[],'source_data_quality':source_quality}

    schemes=[]
    for scheme in ['PMJJBY','PMSBY']:
        src_rows=ss[ss['transaction_type'].eq(scheme)].copy()
        if src_rows.empty:
            continue
        src_rows['period_rate']=src_rows['period'].map(lambda p: _pmjjby_rate_for_period(p) if scheme=='PMJJBY' else PMSBY_COMMISSION_PER_ENROLLMENT)
        if src_rows['period_rate'].isna().any():
            # A missing period-specific rate is unresolved, not zero or a guessed rate.
            continue
        src_rows['expected_row_commission']=pd.to_numeric(src_rows['count'],errors='coerce')*pd.to_numeric(src_rows['period_rate'],errors='coerce')
        src=src_rows.groupby('csp_id',as_index=False).agg(source_count=('count','sum'),expected_commission=('expected_row_commission','sum'))
        rr=r[(r['transaction_type'].eq(scheme)) | (r['transaction_type'].isna() & r['join_type'].eq(scheme))].copy()
        rr['csp_id']=map_unique(rr['csp_id'], norm)
        bc=rr.groupby('csp_id',as_index=False).agg(bc_count=('report_base','sum'),actual_commission=('actual_commission','sum'))
        keys=pd.DataFrame({'csp_id':sorted(set(src['csp_id']).union(set(bc['csp_id'])))})
        x=keys.merge(src,on='csp_id',how='left').merge(bc,on='csp_id',how='left').fillna({'source_count':0,'expected_commission':0,'bc_count':0,'actual_commission':0})
        for col in ['source_count','bc_count','actual_commission','expected_commission']:
            x[col]=pd.to_numeric(x[col],errors='coerce').fillna(0)
        x['count_difference']=x['source_count']-x['bc_count']
        x['commission_difference_bc_minus_expected']=x['actual_commission']-x['expected_commission']
        def status(z):
            if abs(z['count_difference'])<1e-9 and abs(z['commission_difference_bc_minus_expected'])<0.005: return 'MATCHED'
            if z['commission_difference_bc_minus_expected']>0.005: return 'BC EXCESS'
            if z['commission_difference_bc_minus_expected']<-0.005: return 'BC SHORT'
            return 'COUNT MISMATCH'
        x['status']=x.apply(status,axis=1)
        x['transaction_type']=scheme
        schemes.append({
            'transaction_type':scheme,
            'source_transactions':int(x['source_count'].sum()),
            'bc_transactions':int(x['bc_count'].sum()),
            'transaction_difference':int(x['bc_count'].sum()-x['source_count'].sum()),
            'expected_commission':round(float(x['expected_commission'].sum()),2),
            'actual_commission':round(float(x['actual_commission'].sum()),2),
            'commission_difference_bc_minus_expected':round(float(x['commission_difference_bc_minus_expected'].sum()),2),
            'matched_csp_count':int((x['status']=='MATCHED').sum()),
            'bc_excess_csp_count':int((x['status']=='BC EXCESS').sum()),
            'bc_short_csp_count':int((x['status']=='BC SHORT').sum()),
            'count_mismatch_csp_count':int((x['status']=='COUNT MISMATCH').sum()),
        })
        for _,z in x.iterrows():
            schemes[-1].setdefault('rows',[]).append({
                'csp_id':z['csp_id'],'transaction_type':scheme,
                'source_count':int(z['source_count']),'bc_count':int(z['bc_count']),
                'count_difference':int(z['count_difference']),
                'expected_commission':round(float(z['expected_commission']),2),
                'actual_commission':round(float(z['actual_commission']),2),
                'commission_difference_bc_minus_expected':round(float(z['commission_difference_bc_minus_expected']),2),
                'status':z['status']
            })
    all_rows=[row for sch in schemes for row in sch.pop('rows')]
    total={
        'transaction_type':'TOTAL',
        'source_transactions':sum(s['source_transactions'] for s in schemes),
        'bc_transactions':sum(s['bc_transactions'] for s in schemes),
        'transaction_difference':sum(s['transaction_difference'] for s in schemes),
        'expected_commission':round(sum(s['expected_commission'] for s in schemes),2),
        'actual_commission':round(sum(s['actual_commission'] for s in schemes),2),
        'commission_difference_bc_minus_expected':round(sum(s['commission_difference_bc_minus_expected'] for s in schemes),2),
        'matched_csp_count':None,'bc_excess_csp_count':None,'bc_short_csp_count':None,'count_mismatch_csp_count':None
    }
    # No historical CSP roster is consulted here. Zero-activity CSPs must come
    # from an explicitly uploaded current-period source, never a bundled legacy master.
    master_ids=set()
    combined=pd.DataFrame(all_rows)
    if not combined.empty or master_ids:
        by=combined.groupby('csp_id',as_index=False).agg(source_count=('source_count','sum'),bc_count=('bc_count','sum'),expected_commission=('expected_commission','sum'),actual_commission=('actual_commission','sum')) if not combined.empty else pd.DataFrame(columns=['csp_id','source_count','bc_count','expected_commission','actual_commission'])
        if master_ids:
            missing=master_ids-set(by.get('csp_id',pd.Series(dtype=str)))
            if missing:
                by=pd.concat([by,pd.DataFrame({'csp_id':sorted(missing),'source_count':0,'bc_count':0,'expected_commission':0.0,'actual_commission':0.0})],ignore_index=True)
        by['diff']=by['actual_commission']-by['expected_commission']; count_diff=by['source_count']-by['bc_count']
        total['matched_csp_count']=int(((count_diff.abs()<1e-9)&(by['diff'].abs()<0.005)).sum())
        total['bc_excess_csp_count']=int((by['diff']>0.005).sum())
        total['bc_short_csp_count']=int((by['diff']<-0.005).sum())
        total['count_mismatch_csp_count']=int(((count_diff.abs()>1e-9)&(by['diff'].abs()<=0.005)).sum())
    return {'available':True,'schemes':schemes,'total':total,'rows':all_rows,'source_data_quality':source_quality}

def _group_aggregate(df, keys, spec):
    """Vectorized named aggregation: spec is [(output, column, how)].

    how is 'sum', 'first', 'max' or 'sum_min1' (sum that stays blank when every
    value in the group is blank, i.e. Series.sum(min_count=1)).
    """
    g=df.groupby(keys,dropna=False)
    cols={}
    for out,col,how in spec:
        cols[out]=g[col].sum(min_count=1) if how=='sum_min1' else g[col].agg(how)
    return pd.DataFrame(cols).reset_index()

def aggregate_by_csp_and_type(r):
    x=r[r.successful_transactions>0].copy()
    for col in ('actual_comparable_commission','actual_commission','financial_gap','report_base','count_variance'):
        x[col]=pd.to_numeric(x[col],errors='coerce')
    return _group_aggregate(x,['csp_id','transaction_type'],[
        ('successful_transactions','successful_transactions','sum'),
        ('transaction_amount','transaction_amount','sum'),
        ('expected_commission','expected_commission','sum_min1'),
        ('verified_expected_commission','verified_expected_commission','sum_min1'),
        ('actual_commission','actual_comparable_commission','sum_min1'),
        ('actual_transaction_activity_commission','actual_commission','sum_min1'),
        ('financial_gap','financial_gap','sum_min1'),
        ('variance','financial_gap','sum_min1'),
        ('report_base','report_base','sum_min1'),
        ('count_variance','count_variance','sum_min1'),
        ('reconciliation_status','reconciliation_status','first'),
        ('financial_gap_status','financial_gap_status','first'),
        ('exception_flag','exception_flag','max'),
        ('investigation_status','investigation_status','first'),
        ('mismatch_reason','mismatch_reason','first'),
    ])

# ---------------------------------------------------------------------------
# SBI condition audit
# ---------------------------------------------------------------------------
def build_condition_audit(transactions, rate_rules, commission=None):
    """Audit every successful transaction against the SBI commercial rules.

    This is intentionally stricter than the monetary reconciliation. A transaction
    is only marked OK when one deterministic rule is applicable and its commercial
    status is confirmed. Mapping-to-confirm, ambiguous, missing geography, missing
    fee/evidence, and unresolved rule statuses are never silently converted to zero.
    """
    tx=transactions.copy()
    tx['csp_id']=map_unique(tx['csp_id'], norm)
    tx['transaction_type']=map_unique(tx['transaction_type'], norm)
    if 'kyc_type' in tx.columns:
        from .rate_master import _normalize_kyc
        tx['kyc_type']=tx['kyc_type'].map(_normalize_kyc)
    else:
        tx['kyc_type']=''
    tx['amount']=parse_numeric_series(tx['amount'])
    tx['transaction_date']=parse_date_series(tx['transaction_date']) if 'transaction_date' in tx else pd.Series(pd.NaT,index=tx.index)
    cm_ref=build_reference_type_map(commission) if commission is not None else {}
    rm_ref=build_reference_type_map(rate_rules) if rate_rules is not None else {}
    ref_map=dict(cm_ref); ref_map.update({k:v for k,v in rm_ref.items() if k not in ref_map})
    tx['join_type']=resolve_transaction_types_series(tx['transaction_type'],tx['amount'],tx['transaction_date'],ref_map)
    tx['mapping_confidence']=mapping_confidence_series(tx['transaction_type'])
    tx['rule_type']=tx['join_type']
    # INITIAL DEPOSIT has two identities: the bucket is used for BC-source
    # comparison, while the SBI rate master uses the parent PMJDY product.
    tx.loc[tx['transaction_type'].eq('INITIAL DEPOSIT'),'rule_type']=ACCOUNT_OPEN_RULE
    mapped=tx[tx['join_type'].notna()].copy()
    if rate_rules is not None and not rate_rules.empty and not mapped.empty:
        mapped['rule_type']=mapped['join_type']
        mapped.loc[mapped['transaction_type'].eq('INITIAL DEPOSIT'),'rule_type']=ACCOUNT_OPEN_RULE
        mapped,info=add_expected_commission(mapped,rate_rules)
    else:
        mapped['expected_commission']=pd.NA; mapped['commission_rule_id']=pd.NA; mapped['rate_status']='Rate Master Missing'
    for c in ['expected_commission','commission_rule_id','rate_status']:
        if c not in mapped.columns: mapped[c]=pd.NA
    tx[['expected_commission','commission_rule_id','rate_status']]=pd.NA
    tx.loc[mapped.index,['expected_commission','commission_rule_id','rate_status']]=mapped[['expected_commission','commission_rule_id','rate_status']]
    tx['condition_status']='UNMAPPED'
    tx['condition_reason']='No exact approved commercial mapping found for this source transaction type.'
    tx['calculation_basis']=''
    tx.loc[tx['join_type'].notna(),'condition_status']='CONDITIONAL'
    tx.loc[tx['join_type'].notna(),'condition_reason']='Commercial rule mapped but transaction is not yet fully verified for settlement.'

    # Confirmed, deterministic applications and explicit failure/evidence states.
    applied=on_unique(tx['rate_status'].astype('string').fillna(''), lambda x: x.str.startswith('Applied'))
    pending=on_unique(tx['rate_status'].astype('string').fillna(''), lambda x: x.str.contains('Pending Mapping',na=False))
    condition_failed=tx['rate_status'].eq('Condition Failed')
    kyc_required=tx['rate_status'].eq('KYC Evidence Required')
    geography_required=tx['rate_status'].eq('Geography Required')
    rule_missing=tx['rate_status'].eq('Rate Master Missing')
    tx.loc[applied & ~pending,'condition_status']='OK'
    tx.loc[applied & ~pending,'condition_reason']='A single deterministic SBI rule matched the transaction amount/date/geography.'
    tx.loc[applied & ~pending,'calculation_basis']='SBI approved rule/slab'
    tx.loc[pending,'condition_status']='CONDITIONAL'
    tx.loc[pending,'condition_reason']='SBI master marks the product mapping as "Mapping to confirm"; calculated rate is provisional only.'
    tx.loc[pending,'calculation_basis']='SBI rate schedule mapped to product - approval pending'
    # The supplied mapping workbook marks Probable mappings as needing business
    # confirmation. They can be calculated, but they are not final/verified.
    probable_mapping=on_unique(tx['mapping_confidence'].astype('string'), lambda x: x.str.upper()).isin(['PROBABLE','CONDITIONAL'])
    tx.loc[probable_mapping & applied & ~pending,'condition_status']='CONDITIONAL'
    tx.loc[probable_mapping & applied & ~pending,'condition_reason']='Transaction-type mapping is marked Probable in the supplied mapping workbook; rate is calculated provisionally pending business confirmation.'
    tx.loc[probable_mapping & applied & ~pending,'calculation_basis']='SBI rule calculated; transaction-type mapping confirmation required'
    tx.loc[condition_failed,'condition_status']='CONDITION FAIL'
    tx.loc[condition_failed,'condition_reason']='Transaction amount/date does not satisfy any executable SBI rule/slab.'
    tx.loc[condition_failed,'calculation_basis']='SBI condition not met'
    tx.loc[kyc_required,'condition_status']='CONDITIONAL'
    tx.loc[kyc_required,'condition_reason']='SBI account-opening rule requires explicit e-KYC/OVD evidence; current source does not provide usable KYC evidence.'
    tx.loc[kyc_required,'calculation_basis']='SBI CM001-CM006; KYC evidence required'
    tx.loc[geography_required,'condition_status']='CONDITIONAL'
    tx.loc[geography_required,'condition_reason']='SBI rule has geography-dependent rates and the current source does not provide an approved CSP geography.'
    tx.loc[geography_required,'calculation_basis']='SBI Rural/Urban condition; geography evidence required'
    tx.loc[rule_missing & tx['join_type'].notna(),'condition_status']='CONDITIONAL'
    tx.loc[rule_missing & tx['join_type'].notna(),'condition_reason']='Transaction mapping exists, but no executable SBI rate rule is available for this product in the current master.'
    tx.loc[rule_missing & tx['join_type'].notna(),'calculation_basis']='SBI product/rate rule unresolved'

    # Account-opening KYC is an explicit commercial condition. The current
    # Success Transaction source does not contain KYC/OVD evidence, so an
    # INITIAL DEPOSIT row must remain conditional rather than silently using
    # the higher e-KYC slab. If a future upload contains an explicit kyc_type
    # column, CM001-CM004 or CM005-CM006 will be selected deterministically.
    initial=tx['transaction_type'].eq('INITIAL DEPOSIT')
    missing_kyc=initial & tx['kyc_type'].eq('')
    tx.loc[missing_kyc,'condition_status']='CONDITIONAL'
    tx.loc[missing_kyc,'condition_reason']='Account-opening rule requires explicit e-KYC/OVD evidence; current transaction source has no usable KYC field.'
    tx.loc[missing_kyc,'calculation_basis']='SBI CM001-CM006; KYC evidence missing'

    # Amount/rule diagnostics for rows where no rule applied. This distinguishes a
    # genuine condition failure (e.g. < Rs 100 cash withdrawal) from missing evidence.
    rules=rate_rules.copy() if rate_rules is not None else pd.DataFrame()
    if not rules.empty:
        rules['transaction_type']=map_unique(rules['transaction_type'], norm)
        rules['min_amount']=parse_numeric_series(rules.get('min_amount',pd.Series(pd.NA,index=rules.index)))
        rules['max_amount']=parse_numeric_series(rules.get('max_amount',pd.Series(pd.NA,index=rules.index)))
        rules['effective_from']=parse_date_series(rules['effective_from']) if 'effective_from' in rules else pd.Series(pd.NaT,index=rules.index)
        rules['effective_to']=parse_date_series(rules['effective_to']) if 'effective_to' in rules else pd.Series(pd.NaT,index=rules.index)
        rules['rule_status']=rules.get('rule_status',pd.Series('CONFIRMED',index=rules.index)).astype('string').fillna('')
        executable_status=rules['rule_status'].str.upper().str.startswith('CONFIRMED') | rules['rule_status'].str.upper().eq('MAPPING TO CONFIRM')
        for typ, idx in tx[tx['join_type'].notna() & ~tx['rate_status'].fillna('').astype('string').str.startswith('Applied') & ~tx['rate_status'].fillna('').eq('Ambiguous Rate Rule')].groupby('join_type').groups.items():
            rg=rules[(rules['transaction_type'].eq(norm(typ))) & executable_status]
            if rg.empty: continue
            sub=tx.loc[idx]
            in_any=pd.Series(False,index=idx)
            for _,rr in rg.iterrows():
                m=pd.Series(True,index=idx)
                if pd.notna(rr.get('min_amount')):
                    m &= sub['amount'].notna() & (sub['amount'] > rr['min_amount'] if bool(rr.get('min_exclusive',False)) else sub['amount'] >= rr['min_amount'])
                if pd.notna(rr.get('max_amount')):
                    m &= sub['amount'].notna() & (sub['amount'] < rr['max_amount'] if bool(rr.get('max_exclusive',False)) else sub['amount'] <= rr['max_amount'])
                if pd.notna(rr.get('effective_from')):
                    m &= sub['transaction_date'].notna() & (sub['transaction_date'] >= rr['effective_from'])
                if pd.notna(rr.get('effective_to')):
                    m &= sub['transaction_date'].notna() & (sub['transaction_date'] <= rr['effective_to'])
                in_any |= m
            fail_idx=in_any.index[~in_any]
            if len(fail_idx):
                tx.loc[fail_idx,'condition_status']='CONDITION FAIL'
                tx.loc[fail_idx,'condition_reason']='Transaction amount/date is outside every applicable SBI rule/slab for this product.'
                tx.loc[fail_idx,'calculation_basis']='SBI condition not met'

    # Rows mapped to a product but blocked by a non-executable master status remain
    # conditional; explicit amount/evidence failures above take precedence.
    missing_status=tx['join_type'].notna() & tx['rate_status'].eq('Rate Master Missing')
    if missing_status.any() and not rules.empty:
        status_by_type=rules.groupby('transaction_type')['rule_status'].apply(lambda s:'; '.join(sorted(set(s.astype(str))))).to_dict()
        for i in tx.index[missing_status]:
            typ=tx.at[i,'join_type']; st=status_by_type.get(norm(typ),'')
            if st:
                tx.at[i,'condition_status']='CONDITIONAL'
                tx.at[i,'condition_reason']=f'Applicable SBI product rule is not executable in the current rate master; source status: {st}.'
                tx.at[i,'calculation_basis']='SBI master approval/status required'

    # Evidence gates for products whose commercial rule contains an additional
    # eligibility condition that is not represented in the successful transaction row.
    # A numeric rate match alone is not sufficient for final monthly expected revenue.
    evidence_missing = pd.Series(False, index=tx.index)
    evidence_reason = pd.Series('', index=tx.index, dtype='string')
    # V54: PMJDY/PMJJBY/PMSBY are now explicitly covered by the supplied SBI
    # product-rule schedule. Only products with an additional condition absent
    # from the transaction source remain evidence-gated here.
    m=tx['transaction_type'].eq('BHARAT BILL PAYMENTS')
    evidence_missing |= m
    evidence_reason.loc[m]='BBPS biller category/CCF is missing, so Electricity/Telecom/DTH cannot be selected safely.'
    if evidence_missing.any():
        tx.loc[evidence_missing & tx['condition_status'].ne('CONDITION FAIL'),'condition_status']='CONDITIONAL'
        tx.loc[evidence_missing & tx['condition_status'].ne('CONDITION FAIL'),'condition_reason']=evidence_reason.loc[evidence_missing & tx['condition_status'].ne('CONDITION FAIL')]
        tx.loc[evidence_missing & tx['condition_status'].ne('CONDITION FAIL'),'calculation_basis']='Required SBI eligibility evidence missing'

    # Mapping-to-confirm is always provisional, even when a deterministic rate was
    # calculated. It must never enter the verified monthly expected total.
    pending_types=tx['rate_status'].fillna('').astype('string').str.contains('Pending Mapping',na=False)
    tx.loc[pending_types,'condition_status']='CONDITIONAL'
    tx.loc[pending_types,'condition_reason']='SBI master/product mapping is marked Mapping to confirm; calculated amount is provisional only.'
    tx.loc[pending_types,'calculation_basis']='SBI rate calculated, mapping approval pending'

    # Missing geography is never synthesized. If the unresolved rule has different
    # Rural/Urban values, it stays CONDITIONAL until a real CSP geography source is
    # available. Geography-independent rules have already been applied above.
    unresolved_geo=tx['rate_status'].eq('Geography Required')
    if unresolved_geo.any():
        tx.loc[unresolved_geo,'condition_status']='CONDITIONAL'
        tx.loc[unresolved_geo,'condition_reason']='SBI rule has geography-dependent rates and approved CSP geography is missing.'
        tx.loc[unresolved_geo,'calculation_basis']='Additional CSP geography evidence required'

    tx['verified_expected_commission']=pd.to_numeric(tx['expected_commission'],errors='coerce').where(tx['condition_status'].eq('OK'))
    tx['provisional_expected_commission']=pd.to_numeric(tx['expected_commission'],errors='coerce').where(tx['condition_status'].eq('CONDITIONAL'))
    return tx
