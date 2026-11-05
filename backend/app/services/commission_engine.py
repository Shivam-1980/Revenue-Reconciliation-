"""Deterministic expected-commission engine.

No commission rate is inferred from historical actuals. Expected commission is calculated
only from the approved rate/slab master uploaded by the user.
"""
import copy
import threading

import numpy as np
import pandas as pd

from .rate_master import calculate_expected

# One reconciliation run asks for the same expected-commission calculation twice: once for the matching
# step and once for the condition audit, on the same rows and the same rules (the second frame only lacks
# three bookkeeping columns). The calculation is deterministic, so the second request is answered from the
# first result. The result is reused ONLY when every column the rule engine can read, every row, the index and
# the rules are identical (content-hashed); anything else is calculated again exactly as before.
_NOT_READ = ("bc_join_type", "successful_transactions", "transaction_amount")   # never read by calculate_expected
_MIN_ROWS = 20000
_KEEP_SECONDS = 120
_lock = threading.Lock()
_last = {}


def _hash_frame(frame):
    h = pd.util.hash_pandas_object(frame, index=True).to_numpy()
    return int(h.sum(dtype=np.uint64)), int(np.bitwise_xor.reduce(h)), len(h)


def _fingerprint(df, rules):
    cols = tuple(c for c in df.columns if c not in _NOT_READ)
    try:
        return (cols, _hash_frame(df[list(cols)]), _hash_frame(rules.reset_index(drop=True)), tuple(map(str, df[list(cols)].dtypes)))
    except Exception:                                    # unhashable cell contents: just calculate
        return None


def _forget():
    with _lock:
        _last.clear()


def clear_memo():
    _forget()


def add_expected_commission(df, rules=None):
    if rules is None or rules.empty:
        result=df.copy()
        result['expected_commission']=None
        result['commission_rule_id']=None
        result['rate_status']='Rate Master Missing'
        return result, {'rate_master_configured':False,'missing_rules':len(result),'ambiguous_rules':0,'applied_rules':0}
    if len(df) < _MIN_ROWS:
        return calculate_expected(df, rules)
    key = _fingerprint(df, rules)
    in_cols = list(df.columns)
    with _lock:
        hit = _last.get("entry")
    if key is not None and hit is not None and hit["key"] == key:
        # The stored input may carry extra, never-read columns; the new frame must be exactly that input minus them.
        expected_cols = [c for c in hit["in_cols"] if c in df.columns]
        if in_cols == expected_cols and not any(c in df.columns for c in _NOT_READ if c not in hit["in_cols"]):
            out = hit["out"]
            drop = [c for c in out.columns if c in _NOT_READ and c not in df.columns]
            return out.drop(columns=drop).copy(), copy.deepcopy(hit["info"])
    out, info = calculate_expected(df, rules)
    if key is not None:
        with _lock:
            _last["entry"] = {"key": key, "in_cols": in_cols, "out": out.copy(), "info": copy.deepcopy(info)}
        timer = threading.Timer(_KEEP_SECONDS, _forget)
        timer.daemon = True
        timer.start()
    return out, info
