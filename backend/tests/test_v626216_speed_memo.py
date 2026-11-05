"""Speed work that must never change an answer (V62.6.216): the re-used result and the cached period parser."""
import os
import time

import pytest

from app.services import reconciliation_engine as eng, social_security_rules as ssr
from app.services.result_memo import memo_on_files


def test_memo_reuses_the_answer_until_a_file_changes(tmp_path):
    f = tmp_path / "src.csv"; f.write_text("a")
    calls = []

    @memo_on_files(lambda: [f])
    def slow():
        calls.append(1); return {"rows": [1, 2, 3], "n": f.read_text()}

    first = slow(); first["rows"].append(99)               # a caller changing its copy must not change the stored answer
    second = slow()
    assert len(calls) == 1 and second == {"rows": [1, 2, 3], "n": "a"}
    time.sleep(0.01); f.write_text("bb")                    # new upload -> calculated again
    assert slow()["n"] == "bb" and len(calls) == 2


def test_memo_can_be_switched_off(tmp_path, monkeypatch):
    f = tmp_path / "x"; f.write_text("1"); calls = []

    @memo_on_files(lambda: [f])
    def fn():
        calls.append(1); return 1
    monkeypatch.setenv("EKO_NO_RESULT_MEMO", "1")
    fn(); fn()
    assert len(calls) == 2


@pytest.mark.parametrize("value,month,number", [("2026-09", "2026-09", 9), ("September 2026", "2026-09", 9), ("Sep-2026", "2026-09", 9),
                                                 ("2026-09-15", "2026-09", 9), (" 2026-08 ", "2026-08", 8), ("", None, None), (None, None, None), ("junk", None, None)])
def test_cached_period_parsers_give_the_same_answers(value, month, number):
    assert eng._period_month(value) == month
    assert ssr._period_month(value) == number
    assert eng._period_month(value) == month                # second call comes from the cache
