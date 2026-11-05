"""Regression coverage for pandas nullable boolean conditions passed to numpy.select."""
import numpy as np
import pandas as pd


def test_nullable_string_comparison_is_normalized_before_numpy_select():
    status = pd.Series(["MATCH", pd.NA, "SOURCE_COUNT_DIFFERENCE"], dtype="string")
    condition = status.eq("SOURCE_COUNT_DIFFERENCE")

    # pandas nullable BooleanArray is rejected by numpy.select when it contains pd.NA.
    safe_condition = condition.fillna(False).astype(bool).to_numpy(dtype=bool)
    result = np.select([safe_condition], ["SOURCE_COUNT_DIFFERENCE"], default="MATCH")

    assert result.tolist() == ["MATCH", "MATCH", "SOURCE_COUNT_DIFFERENCE"]
