"""Re-use the answer of an expensive read-only calculation while none of its input files has changed (V62.6.216).

A reconciliation run asks the same supplemental questions (m-ATM, PMJJBY/PMSBY) once for the dashboard and once more to
save the month. The answer depends only on the uploaded files, so the second call gets a copy of the first one's answer.
The key is the size and modified time of the named files plus every file in the data folders an upload or reset can change,
so any new upload, reset or restore makes the next call calculate again.
"""
import copy
import functools
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
_FOLDERS = ("transactions", "commissions", "rate_master", "supplemental", "csp_geography", "rural_csp", "expected_commission_rule", "processing")


def _stat(path):
    try:
        st = os.stat(path)
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), None, None)


def data_signature(extra_paths=()):
    sig = [_stat(BASE_DIR / "data" / "upload_metadata.json")]
    for folder in _FOLDERS:
        root = BASE_DIR / "data" / folder
        try:
            with os.scandir(root) as it:
                sig.extend(sorted(_stat(e.path) for e in it if e.is_file()))
        except OSError:
            sig.append((str(root), None, None))
    sig.extend(_stat(p) for p in extra_paths)
    return tuple(sig)


def memo_on_files(extra_paths):
    """Decorator for a no-argument function: `extra_paths()` returns the files it reads (looked up on every call)."""
    def deco(fn):
        state = {}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if args or kwargs or os.getenv("EKO_NO_RESULT_MEMO"):      # EKO_NO_RESULT_MEMO=1 switches the re-use off (for comparisons)
                return fn(*args, **kwargs)
            key = data_signature(extra_paths())
            hit = state.get("v")
            if hit is not None and hit[0] == key:
                return copy.deepcopy(hit[1])
            out = fn()
            state["v"] = (key, copy.deepcopy(out))
            return out
        wrapper.cache_clear = lambda: state.clear()
        return wrapper
    return deco
