"""Deterministic control-population KPI calculations."""
from typing import Optional, Tuple


def controlled_reconciliation_kpi(
    transaction_matched: int,
    transaction_groups: int,
    rural_matched: int = 0,
    rural_groups: int = 0,
    dfs_matched: int = 0,
    dfs_groups: int = 0,
    women_csp_matched: int = 0,
    women_csp_groups: int = 0,
) -> Tuple[int, int, Optional[float]]:
    """Return (matched controls, total controls, rate percent).

    Transaction, Rural, DFS, and Women CSP controls are separate populations.
    They are combined only when the caller labels the KPI for that exact scope.
    Inputs are clamped
    to non-negative integers; empty populations return None rather than 0%.
    """
    tm = max(0, int(transaction_matched or 0))
    tg = max(0, int(transaction_groups or 0))
    rm = max(0, int(rural_matched or 0))
    rg = max(0, int(rural_groups or 0))
    dm = max(0, int(dfs_matched or 0))
    dg = max(0, int(dfs_groups or 0))
    wm = max(0, int(women_csp_matched or 0))
    wg = max(0, int(women_csp_groups or 0))
    matched = tm + rm + dm + wm
    total = tg + rg + dg + wg
    rate = round(matched / total * 100, 2) if total else None
    return matched, total, rate




def active_csp_month_control_groups(expected_amounts, actual_amounts) -> int:
    """Count only CSP-month incentive controls with source activity or a bank payout.

    Zero-activity source roster entries with no BC payout are informational and
    must not dilute reconciliation KPIs.
    """
    import pandas as pd
    expected = pd.to_numeric(pd.Series(expected_amounts), errors='coerce').fillna(0)
    actual = pd.to_numeric(pd.Series(actual_amounts), errors='coerce').fillna(0)
    length = max(len(expected), len(actual))
    expected = expected.reindex(range(length), fill_value=0)
    actual = actual.reindex(range(length), fill_value=0)
    return int(((expected > 0) | (actual > 0)).sum())

def all_source_control_kpi(
    transaction_matched: int, transaction_groups: int,
    rural_matched: int = 0, rural_groups: int = 0,
    dfs_matched: int = 0, dfs_groups: int = 0,
    social_security_matched: int = 0, social_security_groups: int = 0,
    passbook_matched: int = 0, passbook_groups: int = 0,
    tab_matched: int = 0, tab_groups: int = 0,
    loan_lead_matched: int = 0, loan_lead_groups: int = 0,
    matm_matched: int = 0, matm_groups: int = 0,
) -> Tuple[int, int, Optional[float]]:
    """Combine non-overlapping current-period source controls for the headline KPI.

    PMJJBY/PMSBY and Passbook controls are kept outside the primary transaction
    population by the reconciliation engine. Include them here only when their
    independent source controls are READY. Women CSP Rule 24 is intentionally
    excluded because it is a separate monthly incentive KPI; the caller also keeps
    its count visible separately. Each input must be a control-group count, not a
    transaction row count or money amount.
    """
    values = [
        transaction_matched, transaction_groups, rural_matched, rural_groups,
        dfs_matched, dfs_groups, social_security_matched, social_security_groups,
        passbook_matched, passbook_groups, tab_matched, tab_groups,
        loan_lead_matched, loan_lead_groups, matm_matched, matm_groups,
    ]
    v = [max(0, int(x or 0)) for x in values]
    matched = v[0] + v[2] + v[4] + v[6] + v[8] + v[10] + v[12] + v[14]
    groups = v[1] + v[3] + v[5] + v[7] + v[9] + v[11] + v[13] + v[15]
    rate = round(matched / groups * 100, 2) if groups else None
    return matched, groups, rate



def safe_dfs_headline_controls(matched_controls: int, total_controls: int, unresolved_source_rows: int):
    """Exclude DFS from combined headline when unresolved source IDs could overlap bank-only rows."""
    matched=max(0,int(matched_controls or 0)); total=max(0,int(total_controls or 0)); unresolved=max(0,int(unresolved_source_rows or 0))
    if unresolved:
        return 0,0,False
    return matched,total,True


def rural_control_group_count(rural_master_groups: int, unmapped_paid_csp_groups: int) -> int:
    """Count Rural master controls plus distinct bank-paid CSPs missing from that master."""
    return max(0,int(rural_master_groups or 0))+max(0,int(unmapped_paid_csp_groups or 0))


def all_source_kpi_status(
    transaction_groups: int, rural_ready: bool, dfs_ready: bool,
    social_security_ready: bool, passbook_ready: bool, tab_ready: bool,
    loan_lead_ready: bool = False, matm_ready: bool = False,
    unresolved_identity_rows: int = 0, unresolved_source_rows: int = 0,
) -> tuple[str, list[str]]:
    """Describe completeness of the all-source KPI without hiding missing sources.

    The numeric rate is a rate over the included control populations only. This
    helper prevents that partial rate from being labelled READY when any expected
    source is absent, or when source identity/quality exceptions remain.
    Women CSP Rule 24 is intentionally a separate KPI and is not in this scope.
    """
    expected = {
        'Transactions': int(transaction_groups or 0) > 0,
        'Rural Commission': bool(rural_ready),
        'DFS': bool(dfs_ready),
        'PMJJBY/PMSBY': bool(social_security_ready),
        'Passbook Printing': bool(passbook_ready),
        'TAB Incentive': bool(tab_ready),
        'Loan Lead Generation': bool(loan_lead_ready),
        'm-ATM Cash Incentive': bool(matm_ready),
    }
    missing = [name for name, ready in expected.items() if not ready]
    quality_issues = []
    if int(unresolved_identity_rows or 0) > 0:
        quality_issues.append(f'{int(unresolved_identity_rows)} unresolved CSP identity row(s)')
    if int(unresolved_source_rows or 0) > 0:
        quality_issues.append(f'{int(unresolved_source_rows)} source-quality exception row(s)')
    if not any(expected.values()):
        return 'SOURCE_REQUIRED', missing + quality_issues
    if missing or quality_issues:
        return 'PROVISIONAL', missing + quality_issues
    return 'READY', []


def resolved_dfs_headline_controls(rows, unresolved_source_rows: int = 0):
    """Return a safe DFS headline population, preserving resolvable CSP controls.

    If source identities remain unresolved, include only source-side rows with an
    official CSP ID. Exclude unresolved rows and BC-only rows because they may
    represent the same CSP as an unresolved source row. Caller must mark KPI
    PROVISIONAL when unresolved_source_rows > 0.
    """
    import re
    all_rows = list(rows or [])
    if not int(unresolved_source_rows or 0):
        matched = sum(1 for row in all_rows if str(row.get('status') or '').upper() == 'MATCHED')
        return matched, len(all_rows), bool(all_rows), 'READY' if all_rows else 'SOURCE_REQUIRED'
    eligible = [
        row for row in all_rows
        if re.fullmatch(r'1A85\d{4}', str(row.get('csp_id') or '').strip())
        and str(row.get('status') or '').upper() not in {'BC_ONLY_CSP', 'UNRESOLVED_CSP_ID'}
    ]
    matched = sum(1 for row in eligible if str(row.get('status') or '').upper() == 'MATCHED')
    return matched, len(eligible), bool(eligible), 'PARTIAL_IDENTITY_UNRESOLVED' if eligible else 'EXCLUDED_IDENTITY_UNRESOLVED'
