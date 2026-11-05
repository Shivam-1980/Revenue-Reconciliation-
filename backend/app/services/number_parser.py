import re
import threading
from collections import OrderedDict
from functools import wraps

import numpy as np
import pandas as pd

_MEMO_MIN_ROWS = 5000        # below this parsing is instant; above it the same column is parsed many times per upload/run
_MEMO_SIZE = 8
_memo = OrderedDict()
_memo_lock = threading.Lock()


def _memoized(parse):
    """Parsing is deterministic, so identical column contents give identical results: parse a big column once.

    The key is the column's content hash (not its identity), so a re-read CSV of the same data also hits.
    """
    @wraps(parse)
    def wrapper(series):
        if not isinstance(series, pd.Series) or len(series) < _MEMO_MIN_ROWS:
            return parse(series)
        try:
            key = (parse.__name__, len(series), str(series.dtype), series.name, int(pd.util.hash_pandas_object(series, index=False).sum()))
        except Exception:                                  # unhashable cell values: just parse
            return parse(series)
        with _memo_lock:
            hit = _memo.get(key)
            if hit is not None:
                _memo.move_to_end(key)
        if hit is not None:
            return pd.Series(hit.values.copy(), index=series.index, name=hit.name)
        out = parse(series)
        with _memo_lock:
            _memo[key] = out.copy()
            while len(_memo) > _MEMO_SIZE:
                _memo.popitem(last=False)
        return out
    return wrapper


@_memoized
def parse_numeric_series(series):
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    s=series.astype("string").str.strip()
    neg=s.str.match(r"^\(.*\)$",na=False)
    s=s.str.replace(r"[₹$€£]", "", regex=True)
    s=s.str.replace(r"(?i)\bINR\b", "", regex=True)
    s=s.str.replace(",", "", regex=False).str.replace(" ","",regex=False)
    s=s.str.replace(r"[^0-9.\-+()]", "", regex=True)
    s=s.str.replace(r"[()]", "", regex=True)
    out=pd.to_numeric(s,errors="coerce")
    out.loc[neg & out.notna()]=-out.loc[neg & out.notna()].abs()
    return out


def _fast_common_date_format(s):
    """Infer a common operational date format from a small sample.

    Large banking extracts are usually exported with one consistent format.
    Inferring that format once avoids pandas' expensive per-row mixed-format
    parser while retaining the existing robust fallback for genuinely mixed data.
    """
    sample=s.dropna()
    sample=sample[sample.ne('')]
    if sample.empty:
        return None
    sample=sample.head(2000)
    patterns=(
        (r'^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2} (?:AM|PM)$','%d-%m-%Y %I:%M:%S %p'),
        (r'^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$','%d-%m-%Y %H:%M:%S'),
        (r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} (?:AM|PM)$','%d/%m/%Y %I:%M:%S %p'),
        (r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$','%d/%m/%Y %H:%M:%S'),
        (r'^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?$','%Y-%m-%d %H:%M:%S'),
        (r'^\d{4}/\d{2}/\d{2}(?: \d{2}:\d{2}:\d{2})?$','%Y/%m/%d %H:%M:%S'),
        (r'^\d{2}-\d{2}-\d{4}$','%d-%m-%Y'),
        (r'^\d{2}/\d{2}/\d{4}$','%d/%m/%Y'),
        (r'^\d{8}$','%Y%m%d'),
    )
    import re
    vals=sample.astype(str)
    for pattern,fmt in patterns:
        if bool(vals.str.match(pattern,na=False).all()):
            return fmt
    return None

@_memoized
def parse_date_series(series):
    """Parse common banking/Indian operational dates without month hard-coding.

    Handles ISO, DD-MM-YYYY/DD/MM/YYYY, mixed timestamp strings, Excel serial
    dates, and YYYYMMDD values. A fast exact-format path is used for large
    consistent exports; mixed-format data falls back to the robust parser.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series,errors='coerce')
    s=series.astype('string').str.strip()
    if s.empty:
        return pd.Series(pd.NaT,index=series.index,dtype='datetime64[ns]')

    fmt=_fast_common_date_format(s)
    if fmt:
        out=pd.to_datetime(s,format=fmt,errors='coerce',dayfirst=False)
        # Exact-format parsing should be authoritative when it parsed every
        # nonblank source value. If a rare outlier exists, use the full fallback.
        nonblank=s.ne('') & s.notna()
        if int(out.notna().sum()) >= int(nonblank.sum()):
            return out

    out=pd.Series(pd.NaT,index=series.index,dtype='datetime64[ns]')
    ymd8=s.str.fullmatch(r'\d{8}',na=False)
    if ymd8.any():
        out.loc[ymd8]=pd.to_datetime(s.loc[ymd8],format='%Y%m%d',errors='coerce')
    iso=s.str.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T].*)?$',na=False)
    pending=out.isna() & iso
    if pending.any():
        out.loc[pending]=pd.to_datetime(s.loc[pending],errors='coerce',yearfirst=True,format='mixed')
    numeric=pd.to_numeric(s,errors='coerce')
    excel_mask=out.isna() & numeric.between(20000,80000,inclusive='both')
    if excel_mask.any():
        out.loc[excel_mask]=pd.Timestamp('1899-12-30') + pd.to_timedelta(numeric.loc[excel_mask],unit='D')
    rest=out.isna()
    if rest.any():
        out.loc[rest]=pd.to_datetime(s.loc[rest],errors='coerce',dayfirst=True,format='mixed')
    return out


def map_unique(series, func):
    """``series.map(func)`` for an object column, calling ``func`` once per distinct value instead of once per row.

    Same result as ``series.map(func)`` (func must be deterministic); other dtypes use the plain map.
    """
    if not isinstance(series, pd.Series) or series.dtype != object or len(series) < 2000:
        return series.map(func)
    codes, uniques = pd.factorize(series, use_na_sentinel=True)
    table = np.empty(len(uniques) + 1, dtype=object)
    for i, u in enumerate(uniques):
        table[i] = func(u)
    table[len(uniques)] = func(np.nan)                       # code -1 (missing) lands on the last slot
    return pd.Series(table[codes], index=series.index, name=series.name)
