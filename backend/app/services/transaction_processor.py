import pandas as pd
from .number_parser import parse_date_series
from .fast_text import stripped, stripped_upper

SUCCESS_STATUSES = {"SUCCESS", "SUCCESSFUL", "SUCCEEDED", "COMPLETED", "SUCCESS TRANSACTION", "SUCCESSFUL TRANSACTION"}

def get_successful_transactions(df):
    result=df.copy()
    # Upload validation normally standardizes these fields first. Keep this
    # service defensive as it is also called directly by the dashboard and tests.
    required={"transaction_id", "csp_id", "transaction_type", "amount", "transaction_date"}
    missing=required-set(result.columns)
    if missing:
        raise ValueError("Transaction data missing required normalized columns: " + ", ".join(sorted(missing)))
    if "status" not in result.columns:
        # The upload endpoint is specifically the Successful Transaction File
        # slot; a missing Status column is therefore an explicit success-only
        # source assumption, also recorded by validate_transaction_data.
        result["status"]="SUCCESS"
    result["status"]=stripped_upper(result["status"])
    # Parse dates BEFORE eligibility filtering. A nonblank but invalid date such
    # as '31/19/2026' must not pass merely because the raw cell is non-null.
    result["transaction_date"] = parse_date_series(result["transaction_date"])
    # Preserve every raw row in storage, but only rows with all mandatory financial
    # fields valid enter the eligible successful population. Invalid rows remain in
    # validation/audit counts and are never silently converted to zero.
    ref=result["transaction_id"].astype('string').str.strip()
    csp=stripped(result["csp_id"])
    typ=stripped(result["transaction_type"])
    amount=pd.to_numeric(result["amount"],errors='coerce')
    date_ok=result["transaction_date"].notna()
    valid_fields=amount.notna() & ref.notna() & ref.ne('') & csp.notna() & csp.ne('') & typ.notna() & typ.ne('') & date_ok
    return result[result["status"].isin(SUCCESS_STATUSES) & valid_fields].copy()


# The current transaction file is re-read by the dashboard, reconciliation views and the
# history archive several times per request. Parse it once per file version (path, size,
# modification time) and hand out copies, so callers can never see stale or shared data.
import threading as _threading
from pathlib import Path as _Path

_success_cache = {}
_success_lock = _threading.Lock()


def load_successful_transactions(path):
    path = _Path(path)
    st = path.stat()
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
    with _success_lock:
        cached = _success_cache.get(key)
        if cached is None:
            cached = get_successful_transactions(pd.read_csv(path, low_memory=False))
            _success_cache.clear()
            _success_cache[key] = cached
    return cached.copy()
