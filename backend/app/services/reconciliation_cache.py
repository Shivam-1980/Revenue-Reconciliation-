"""Fast, single-flight cache for deterministic reconciliation results."""
from pathlib import Path
import json
import threading
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / 'data'
CACHE = CACHE_DIR / 'reconciliation_cache.csv'
CACHE_META = CACHE_DIR / 'reconciliation_cache_meta.json'
_LOCK = threading.Lock()


RECONCILIATION_ENGINE_VERSION = '62.6.216-ui-security-speed'

def signature_from_metadata(meta, tx, cm, rm, geo=None):
    import hashlib

    def sig(kind, path):
        item = meta.get(kind) or {}
        # The active file bytes are authoritative. Metadata can lag after manual
        # replacement/recovery, so a stored upload hash must not mask file changes.
        if path is not None and path.exists() and path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            return digest.hexdigest()
        return item.get('sha256')
    return {'engine_version': RECONCILIATION_ENGINE_VERSION, 'transactions': sig('transactions', tx), 'commission': sig('commission', cm), 'rate_master': sig('rate_master', rm), 'csp_geography': sig('csp_geography', geo) if geo is not None else None}


# One request reads the cached result many times (dashboard, aggregates, history snapshot). The file is parsed once per
# version (size + modification time of the data and meta files) and every caller gets its own copy.
_MEMO_LOCK = threading.Lock()
_memo = {}


def _forget_memo():
    with _MEMO_LOCK:
        _memo.clear()


def read_cached(signature):
    if not CACHE.exists() or not CACHE_META.exists():
        return None
    try:
        m = json.loads(CACHE_META.read_text(encoding='utf-8'))
        if m.get('signature') != signature:
            return None
        data, meta = CACHE.stat(), CACHE_META.stat()
        key = (str(CACHE), data.st_size, data.st_mtime_ns, meta.st_size, meta.st_mtime_ns)
        with _MEMO_LOCK:
            hit = _memo.get('entry')
        if hit is not None and hit[0] == key:
            return hit[1].copy()
        frame = pd.read_csv(CACHE, low_memory=False)
        with _MEMO_LOCK:
            _memo['entry'] = (key, frame.copy())
        return frame
    except Exception:
        return None


def write_cached(result, signature):
    _forget_memo()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix('.tmp.csv')
    result.to_csv(tmp, index=False)
    tmp.replace(CACHE)
    CACHE_META.write_text(json.dumps({'signature': signature}, indent=2), encoding='utf-8')


def get_or_compute(signature, compute_fn):
    """Only one request computes a new result; concurrent dashboard calls reuse it."""
    cached = read_cached(signature)
    if cached is not None:
        return cached, True
    with _LOCK:
        cached = read_cached(signature)
        if cached is not None:
            return cached, True
        result = compute_fn()
        write_cached(result, signature)
        return result, False


def clear_cache():
    _forget_memo()
    for p in (CACHE, CACHE_META):
        try: p.unlink()
        except FileNotFoundError: pass
