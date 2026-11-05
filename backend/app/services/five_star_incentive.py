"""Deterministic SBI 5-Star CSP monthly incentive policy.

Rule source: user-provided SBI Expected Commission Rule workbook and screenshot
effective 01-Apr-2025. Rate is ₹500 per CSP-month only when all five criteria
are evidenced. This module does not infer eligibility from payout rows.
"""
from __future__ import annotations

from typing import Any, Mapping

CRITERIA = (
    "a_rating",
    "passbook_printer",
    "micro_atm",
    "uv_lamp",
    "voice_prompt",
)
MONTHLY_RATE_INR = 500.0


def calculate_five_star_incentive(evidence: Mapping[str, Any]) -> dict:
    """Return eligibility and expected monthly incentive from five evidence flags.

    Each criterion must be explicitly True. Missing/unknown flags are not treated
    as False or True; they leave the result evidence-required. Amount is never
    inferred from the BC actual payout.
    """
    normalized = {}
    for key in CRITERIA:
        value = evidence.get(key)
        if isinstance(value, bool):
            normalized[key] = value
        elif value is None or str(value).strip() == "":
            normalized[key] = None
        else:
            text = str(value).strip().lower()
            if text in {"yes", "y", "true", "1", "pass", "eligible"}:
                normalized[key] = True
            elif text in {"no", "n", "false", "0", "fail", "ineligible"}:
                normalized[key] = False
            else:
                normalized[key] = None
    missing = [key for key, value in normalized.items() if value is None]
    failed = [key for key, value in normalized.items() if value is False]
    if missing:
        status = "EVIDENCE_REQUIRED"
        expected = None
    elif failed:
        status = "NOT_ELIGIBLE"
        expected = 0.0
    else:
        status = "ELIGIBLE"
        expected = MONTHLY_RATE_INR
    return {
        "rule_id": "SBI-5STAR-CSP-MONTHLY",
        "frequency": "Monthly",
        "rate_inr": MONTHLY_RATE_INR,
        "status": status,
        "expected_commission": expected,
        "criteria": normalized,
        "missing_criteria": missing,
        "failed_criteria": failed,
        "eligibility_rule": "A-rating AND Passbook Printer AND Micro ATM (m-ATM) AND UV Lamp AND Voice Prompt",
        "source": "SBI rule workbook / user-provided screenshot, effective 2025-04-01",
    }
