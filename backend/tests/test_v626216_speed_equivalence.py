"""The V62.6.216 speed-ups must change timing only: every result equals what the plain code returns."""
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.services import fast_text


def _text_column(n=9000, dtype="string"):
    base = ["SUCCESS", " success ", "Failed", "", "  ", None, "PENDING\t", "ünï", "Applied", "Pending Mapping x"]
    values = [base[i % len(base)] for i in range(n)]
    return pd.Series(values, dtype=dtype if dtype == "string" else object, name="col")


@pytest.mark.parametrize("dtype", ["string", "object"])
@pytest.mark.parametrize("op", [
    lambda s: s.str.strip(),
    lambda s: s.str.strip().str.upper(),
    lambda s: s.str.startswith("Applied"),
    lambda s: s.str.contains("Pending Mapping", na=False),
    lambda s: s.str.strip().eq(""),
])
def test_on_unique_equals_the_plain_operation(dtype, op):
    s = _text_column(dtype=dtype)
    s.index = pd.RangeIndex(100, 100 + len(s))                     # a non-default index must be kept
    expected = op(s)
    got = fast_text.on_unique(s, op)
    pd.testing.assert_series_equal(got, expected)


def test_on_unique_falls_back_for_small_and_high_cardinality_columns():
    small = _text_column(100)
    pd.testing.assert_series_equal(fast_text.on_unique(small, lambda s: s.str.strip()), small.str.strip())
    unique_ids = pd.Series([f" id{i} " for i in range(9000)], dtype="string")
    pd.testing.assert_series_equal(fast_text.on_unique(unique_ids, lambda s: s.str.strip()), unique_ids.str.strip())
    numbers = pd.Series(np.arange(9000))                            # not text: untouched
    pd.testing.assert_series_equal(fast_text.on_unique(numbers, lambda s: s + 1), numbers + 1)


def test_stripped_helpers_match_pandas():
    s = _text_column()
    pd.testing.assert_series_equal(fast_text.stripped(s), s.astype("string").str.strip())
    pd.testing.assert_series_equal(fast_text.stripped_upper(s), s.astype("string").str.strip().str.upper())


def _transactions(n=7000):
    rng = np.random.default_rng(3)
    csp = rng.choice(["CSP1", " csp2 ", "Csp3", "", None, "CSP4"], n)
    typ = rng.choice(["CASH WITHDRAWAL", " Cash Deposit ", "Balance Enquiry", "", None, "INITIAL DEPOSIT"], n)
    status = rng.choice(["SUCCESS", " success", "FAILED", "", None, "Completed"], n)
    return pd.DataFrame({
        "transaction_id": [f"T{i}" if i % 97 else f"T{i - 1}" for i in range(n)],         # a few duplicates
        "csp_id": csp, "transaction_type": typ, "status": status,
        "amount": rng.choice(["100", "250.5", "(30)", "abc", "", None, "1,200"], n),
        "transaction_date": rng.choice(["2026-09-01 10:00:00", "2026-09-15 09:30:00", "bad", None], n),
    })


def test_validation_and_snapshot_equal_the_plain_path(monkeypatch):
    from app.services.validator import validate_transaction_data
    from app.services.processing_snapshot import build_snapshot
    from app.services.transaction_processor import get_successful_transactions

    def everything():
        df, v = validate_transaction_data(_transactions())
        std = get_successful_transactions(df)
        snap = build_snapshot(df, None)
        return v, std, snap

    fast_v, fast_std, fast_snap = everything()
    monkeypatch.setattr(fast_text, "_MIN_ROWS", 10 ** 9)           # no value-at-a-time shortcut: the plain pandas code
    plain_v, plain_std, plain_snap = everything()
    assert fast_v == plain_v
    assert fast_snap == plain_snap
    pd.testing.assert_frame_equal(fast_std, plain_std)
    assert fast_v["processable_rows"] > 0 and fast_v["missing_csp"] > 0 and fast_v["missing_transaction_date"] > 0


def test_expected_commission_text_handling_equals_the_plain_path(monkeypatch):
    from app.services.rate_master import calculate_expected
    n = 6500
    rng = np.random.default_rng(5)
    tx = pd.DataFrame({
        "rule_type": rng.choice(["CASH WITHDRAWAL", "CASH DEPOSIT", "ACCOUNT OPPENING (PMJDY) WITH E-KYC", "ACCOUNT OPPENING WITHOUT EKYC", "BALANCE ENQUIRY"], n),
        "csp_id": rng.choice(["A1", "a2", " A3 "], n),
        "amount": rng.integers(50, 20000, n).astype(float),
        "transaction_date": pd.Timestamp("2026-09-01") + pd.to_timedelta(rng.integers(0, 29 * 86400, n), unit="s"),
        "channel": rng.choice(["RURAL", "URBAN", "", "semi urban"], n),
    })
    rules = pd.DataFrame({
        "transaction_type": ["CASH WITHDRAWAL", "CASH WITHDRAWAL", "CASH DEPOSIT", "BALANCE ENQUIRY"],
        "rate": [1.0, 2.0, 5.0, 3.0], "rate_type": ["PERCENTAGE", "FIXED", "FIXED", "FIXED"],
        "min_amount": [0, 1000, None, None], "max_amount": [999.99, None, None, None],
        "channel": ["", "", "RURAL", ""], "commercial_scope": ["TRANSACTION"] * 4,
    })
    fast_out, fast_info = calculate_expected(tx.copy(), rules.copy())
    monkeypatch.setattr(fast_text, "_MIN_ROWS", 10 ** 9)
    plain_out, plain_info = calculate_expected(tx.copy(), rules.copy())
    pd.testing.assert_frame_equal(fast_out, plain_out)
    assert fast_info == plain_info


def test_parse_dates_of_real_datetimes_equals_the_text_round_trip():
    from app.services.rate_master import _parse_dates
    stamps = pd.Series(pd.to_datetime(["2026-09-01 10:11:12", "2026-09-30 00:00:00", None, "2026-01-05 23:59:59"]), name="transaction_date")
    fractions = pd.Series(pd.to_datetime(["2026-09-01 10:11:12.123456", "2026-09-02 10:11:13.5", None]))
    midnight = pd.Series(pd.to_datetime(["2026-09-01", "2026-09-02", None]))
    for s in (stamps, fractions, midnight):
        via_text = _parse_dates(s.astype("string"))                 # the path used for text columns
        direct = _parse_dates(s)
        pd.testing.assert_series_equal(direct, via_text)


def _reference_safe(value):
    """The snapshot cleaner as it was before V62.6.216."""
    import pandas as pd_
    if type(value) in (str, int, bool, type(None)):
        return value
    if value is pd_.NA or value is pd_.NaT: return None
    if isinstance(value, np.bool_): return bool(value)
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value); return x if math.isfinite(x) else None
    if isinstance(value, (pd_.Timestamp, datetime)): return value.isoformat()
    if isinstance(value, dict): return {str(k): _reference_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [_reference_safe(v) for v in value]
    if hasattr(value, "item"):
        try: return _reference_safe(value.item())
        except Exception: pass
    return value


def test_snapshot_cleaner_equals_the_reference_cleaner():
    from app.api.reconciliation_history import _safe
    samples = [
        1.5, -0.0, 0.0, 1e308, float("nan"), float("inf"), float("-inf"), np.float64(2.5), np.float32(3.5), np.float64("nan"),
        7, True, None, "text", np.int64(9), np.bool_(True), pd.NA, pd.NaT,
        pd.Timestamp("2026-09-01 10:00:00"), datetime(2026, 9, 1, tzinfo=timezone.utc),
        {"a": 1.25, 2: float("nan"), "n": {"x": [1, float("inf"), np.float64(4.5), (1, 2)]}},
        [1.5, [float("nan"), {"k": np.int64(3)}], (np.float64(1.0),)],
        {1: "int key", None: "none key", 2.5: "float key"},
        [], {}, ("t", 1.5),
    ]
    for value in samples:
        got, want = _safe(value), _reference_safe(value)
        assert repr(got) == repr(want), value


def test_cached_result_is_parsed_once_per_file_version_and_copies_are_independent(tmp_path, monkeypatch):
    from app.services import reconciliation_cache as rc
    monkeypatch.setattr(rc, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(rc, "CACHE", tmp_path / "reconciliation_cache.csv")
    monkeypatch.setattr(rc, "CACHE_META", tmp_path / "reconciliation_cache_meta.json")
    rc._forget_memo()
    sig = {"transactions": "abc"}
    frame = pd.DataFrame({"csp_id": ["A", "B"], "expected_commission": [1.5, np.nan]})
    rc.write_cached(frame, sig)

    reads = []
    real_read = pd.read_csv
    monkeypatch.setattr(pd, "read_csv", lambda *a, **k: (reads.append(1), real_read(*a, **k))[1])
    first = rc.read_cached(sig)
    second = rc.read_cached(sig)
    assert len(reads) == 1
    pd.testing.assert_frame_equal(first, real_read(rc.CACHE, low_memory=False))
    pd.testing.assert_frame_equal(first, second)
    second.loc[0, "csp_id"] = "CHANGED"                                  # a caller changing its copy must not leak
    pd.testing.assert_frame_equal(rc.read_cached(sig), first)

    assert rc.read_cached({"transactions": "other"}) is None              # another source version is a miss
    rc.write_cached(pd.DataFrame({"csp_id": ["Z"], "expected_commission": [9.0]}), sig)
    assert rc.read_cached(sig)["csp_id"].tolist() == ["Z"]               # a rewritten cache is not served from the memo
    rc.clear_cache()
    assert rc.read_cached(sig) is None
