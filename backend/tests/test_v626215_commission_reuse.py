"""The second, identical expected-commission request of a run is answered from the first; anything different is recalculated."""
import numpy as np
import pandas as pd
import pytest

from app.services import commission_engine as ce


@pytest.fixture
def engine(monkeypatch):
    calls = []

    def fake(df, rules):
        calls.append(len(df))
        out = df.copy()
        out["csp_id"] = out["csp_id"].astype(str).str.upper()                  # like the real one: also rewrites existing columns
        out["expected_commission"] = out["amount"] * 0.01
        out["rate_status"] = "ok"
        return out, {"applied_rules": len(df)}

    monkeypatch.setattr(ce, "calculate_expected", fake)
    ce.clear_memo()
    yield calls
    ce.clear_memo()


def _frame(n=30000, extras=True):
    df = pd.DataFrame({"csp_id": [f"a{i % 50}" for i in range(n)], "amount": np.arange(n, dtype=float), "rule_type": ["X"] * n})
    if extras:
        df["bc_join_type"] = "J"; df["successful_transactions"] = 1; df["transaction_amount"] = df["amount"]
    return df


RULES = pd.DataFrame({"transaction_type": ["X"], "rate": [1.0]})


def test_second_identical_request_is_reused_and_equals_a_fresh_calculation(engine):
    first_in, second_in = _frame(extras=True), _frame(extras=False)
    out1, info1 = ce.add_expected_commission(first_in, RULES)
    out2, info2 = ce.add_expected_commission(second_in, RULES)
    assert engine == [30000]                                                    # calculated once
    ce.clear_memo()
    fresh, fresh_info = ce.add_expected_commission(_frame(extras=False), RULES)
    assert engine == [30000, 30000]
    pd.testing.assert_frame_equal(out2, fresh)
    assert info2 == fresh_info and list(out2.columns) == list(fresh.columns)
    assert not {"bc_join_type", "successful_transactions", "transaction_amount"} & set(out2.columns)
    out2.loc[0, "expected_commission"] = -1                                     # a caller changing its copy must not change the memo
    out3, _ = ce.add_expected_commission(_frame(extras=False), RULES)
    assert out3.loc[0, "expected_commission"] == 0


def test_any_difference_forces_a_recalculation(engine):
    ce.add_expected_commission(_frame(extras=True), RULES)
    changed = _frame(extras=False); changed.loc[7, "amount"] = 999.0
    ce.add_expected_commission(changed, RULES)
    other_rules = RULES.copy(); other_rules.loc[0, "rate"] = 2.0
    ce.add_expected_commission(_frame(extras=False), other_rules)
    reordered = _frame(extras=False)[["amount", "csp_id", "rule_type"]]
    ce.add_expected_commission(reordered, RULES)
    assert len(engine) == 4


def test_small_frames_are_never_memoized(engine):
    small = _frame(n=100)
    ce.add_expected_commission(small, RULES); ce.add_expected_commission(small, RULES)
    assert engine == [100, 100]
