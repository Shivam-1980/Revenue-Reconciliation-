"""Permanent SBI PMJJBY/PMSBY commission policy based on user-supplied SBI rule image.

PMJJBY commission depends on the enrollment/report month quarter. PMSBY pays a
fixed ₹1 commission per qualifying enrollment throughout the annual cover cycle.
All calculations are deterministic; no AI inference is used for financial values.
"""
from __future__ import annotations
from functools import lru_cache
import re
import pandas as pd

PMSBY_COMMISSION_PER_ENROLLMENT = 1.0
PMSBY_ANNUAL_PREMIUM = 20.0
PMSBY_COVER_START_MONTH = 6  # 1 June
PMSBY_COVER_END_MONTH = 5    # 31 May of following year

# Premium -> allowed calendar months for PMJJBY, exactly as supplied in the rule image.
PMJJBY_PREMIUM_MONTHS = {
    436.0: {6, 7, 8},
    342.0: {9, 10, 11},
    228.0: {12, 1, 2},
    114.0: {3, 4, 5},
}
PMJJBY_COMMISSION_BY_MONTH = {
    **{m: 30.0 for m in (6, 7, 8)},
    **{m: 22.5 for m in (9, 10, 11)},
    **{m: 15.0 for m in (12, 1, 2)},
    **{m: 7.5 for m in (3, 4, 5)},
}

def _period_month(period_value):
    if period_value is None:
        return None
    raw = str(period_value).strip()
    if not raw:
        return None
    return _period_month_of_text(raw)


@lru_cache(maxsize=4096)
def _period_month_of_text(raw):
    parsed = pd.to_datetime(raw, errors="coerce", dayfirst=False)
    if pd.notna(parsed):
        return int(parsed.month)
    for fmt in ("%B %Y", "%b %Y", "%B-%Y", "%b-%Y"):
        try:
            return int(pd.to_datetime(raw, format=fmt).month)
        except Exception:
            pass
    match = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if match:
        return int(match.group(2))
    return None

def pmjjby_rate_for_period(period_value):
    """Return PMJJBY commission per enrollment for the period month, or None if unknown."""
    month = _period_month(period_value)
    return PMJJBY_COMMISSION_BY_MONTH.get(month) if month is not None else None

def pmsby_rate_for_period(period_value):
    """PMSBY commission per enrollment is ₹1 in every month of the June-May cycle."""
    month = _period_month(period_value)
    return PMSBY_COMMISSION_PER_ENROLLMENT if month in set(range(1, 13)) else None

def pmjjby_premium_is_valid_for_period(premium, period_value):
    """Validate PMJJBY premium/month combination without guessing unknown periods."""
    month = _period_month(period_value)
    if month is None:
        return False
    try:
        amount = float(premium)
    except (TypeError, ValueError):
        return False
    return any(abs(amount - valid_premium) < 0.005 and month in months
               for valid_premium, months in PMJJBY_PREMIUM_MONTHS.items())
