"""Column parsing is memoized for big columns; results must equal the uncached parse and never alias each other."""
import numpy as np
import pandas as pd

from app.services import number_parser as np_


def _big(n=6000):
    d = pd.Series(["01-09-2026 10:11:12"] * (n - 3) + ["2026-09-30", "bad", None], name="transaction_date")
    a = pd.Series(["1,200.50"] * (n - 3) + ["(30)", "x", None], name="amount")
    return d, a


def test_memoized_results_equal_fresh_parse_and_survive_mutation():
    d, a = _big()
    np_._memo.clear()
    fresh_d = np_.parse_date_series.__wrapped__(d)
    fresh_a = np_.parse_numeric_series.__wrapped__(a)
    first_d, first_a = np_.parse_date_series(d), np_.parse_numeric_series(a)
    second_d, second_a = np_.parse_date_series(d), np_.parse_numeric_series(a)       # cache hits
    pd.testing.assert_series_equal(first_d, fresh_d); pd.testing.assert_series_equal(second_d, fresh_d)
    pd.testing.assert_series_equal(first_a, fresh_a); pd.testing.assert_series_equal(second_a, fresh_a)
    second_d.iloc[0] = pd.NaT; second_a.iloc[0] = np.nan                               # mutating a result must not poison the cache
    pd.testing.assert_series_equal(np_.parse_date_series(d), fresh_d)
    pd.testing.assert_series_equal(np_.parse_numeric_series(a), fresh_a)


def test_hit_follows_the_callers_index_and_different_content_misses():
    d, _ = _big()
    np_._memo.clear()
    np_.parse_date_series(d)
    shifted = d.copy(); shifted.index = shifted.index + 10
    out = np_.parse_date_series(shifted)
    assert list(out.index) == list(shifted.index)
    other = d.copy(); other.iloc[0] = "02-09-2026 00:00:00"
    assert np_.parse_date_series(other).iloc[0] == pd.Timestamp("2026-09-02")


def test_map_unique_equals_plain_map_for_every_kind_of_cell():
    from app.services.rate_master import norm
    vals = ["  upc  cash-in ", "UPC CASH-IN", None, np.nan, pd.NA, 12, 3.5, "", "x\ty", " ", "Ünï"] * 400
    s = pd.Series(vals, name="t", index=range(100, 100 + len(vals)), dtype=object)
    pd.testing.assert_series_equal(np_.map_unique(s, norm), s.map(norm))
    string_dtype = s.astype("string")
    pd.testing.assert_series_equal(np_.map_unique(string_dtype, norm), string_dtype.map(norm))     # other dtypes: plain map
    small = s.head(10)
    pd.testing.assert_series_equal(np_.map_unique(small, norm), small.map(norm))
