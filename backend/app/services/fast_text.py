"""Element-wise text operations computed once per distinct value instead of once per row.

pandas runs `.str` methods on a `string` column as a Python loop. Columns such as CSP, transaction type, status
or rate_status hold a few hundred distinct values in hundreds of thousands of rows, so the same text is processed
over and over. ``on_unique`` applies the operation to the distinct values (missing values included) and spreads
the result back, giving exactly what ``op(series)`` returns. ``op`` must be element-wise.
"""
import numpy as np
import pandas as pd

_MIN_ROWS = 5000
_MAX_UNIQUE_SHARE = 0.25        # above this the saving is small; run the plain operation


def on_unique(series, op):
    is_string = isinstance(series, pd.Series) and isinstance(series.dtype, pd.StringDtype)
    if not isinstance(series, pd.Series) or len(series) < _MIN_ROWS or not (is_string or series.dtype == object):
        return op(series)
    try:
        codes, uniques = pd.factorize(series, use_na_sentinel=True)
    except TypeError:                                   # unhashable cell contents: just run the operation
        return op(series)
    if len(uniques) > len(series) * _MAX_UNIQUE_SHARE:
        return op(series)
    # missing values: pd.NA in a string column, NaN in an object column (as `.str` methods see them)
    if is_string:
        distinct = pd.Series(pd.array(list(uniques) + [pd.NA], dtype=series.dtype), name=series.name)
    else:
        distinct = pd.Series(np.array(list(uniques) + [np.nan], dtype=object), name=series.name)
    result = op(distinct)
    slot = np.where(codes < 0, len(uniques), codes)
    return pd.Series(result.array.take(slot), index=series.index, name=result.name)


def stripped(series):
    """Same as ``series.astype('string').str.strip()``."""
    return on_unique(series.astype('string'), lambda s: s.str.strip())


def stripped_upper(series):
    """Same as ``series.astype('string').str.strip().str.upper()``."""
    return on_unique(series.astype('string'), lambda s: s.str.strip().str.upper())
