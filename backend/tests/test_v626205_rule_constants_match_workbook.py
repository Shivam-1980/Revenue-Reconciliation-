"""Hardcoded incentive constants must match the permanent SBI rule workbook.

Several incentive services carry their rate/cap as Python constants. If SBI's
approved workbook changes, these tests fail instead of letting code silently drift.
"""
import re
from pathlib import Path

import pandas as pd
import pytest

from app.api import upload
from app.services import five_star_incentive, rural_commission, women_csp_incentive

WORKBOOK = Path(__file__).resolve().parents[1] / "app" / "data" / "expected_commission_rule" / "latest.xlsx"


@pytest.fixture(scope="module")
def master():
    df = pd.read_excel(WORKBOOK, sheet_name="Consolidated Commission Master", header=None).astype(str)
    return {row[1].strip(): row for row in df.itertuples(index=False)}


def _numbers(text):
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def _row(master, component):
    assert component in master, f"'{component}' missing from rule workbook"
    row = master[component]
    return row[2], row[3], row[4]  # condition, rural, urban


def test_women_csp_rule24(master):
    _, rural, urban = _row(master, "Women CSP Incentive")
    for cell in (rural, urban):
        assert _numbers(cell) == [women_csp_incentive.RATE * 100, women_csp_incentive.MONTHLY_CAP]


def test_matm_cash_incentive(master):
    _, rural, urban = _row(master, "Micro ATM (m-ATM) Cash Incentive")
    for cell in (rural, urban):
        assert _numbers(cell) == [upload.MATM_RATE, upload.MATM_CAP]


def test_tab_incentive(master):
    _, rural, urban = _row(master, "TAB Financial Transaction Incentive")
    for cell in (rural, urban):
        assert _numbers(cell) == [upload.TAB_RATE, upload.TAB_CAP]


def test_rural_csp_incentive(master):
    condition, rural, urban = _row(master, "Rural CSP Incentive")
    assert _numbers(rural) == [rural_commission.RURAL_INCENTIVE_AMOUNT]
    assert "not applicable" in urban.lower()
    assert _numbers(condition) == [
        rural_commission.RURAL_MIN_LOGIN_DAYS, rural_commission.RURAL_MIN_PMJDY, rural_commission.RURAL_MIN_TXN,
    ]
    assert "OR" in condition and "AND" in condition


def test_five_star_incentive(master):
    _, rural, urban = _row(master, "5 STAR CSP Incentive")
    for cell in (rural, urban):
        assert _numbers(cell) == [five_star_incentive.MONTHLY_RATE_INR]
