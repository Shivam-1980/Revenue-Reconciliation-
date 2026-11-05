from app.services.control_kpi import safe_dfs_headline_controls, rural_control_group_count, all_source_kpi_status, resolved_dfs_headline_controls

def test_dfs_with_unresolved_source_ids_is_not_added_to_combined_headline():
    assert safe_dfs_headline_controls(98, 157, 23) == (0, 0, False)

def test_dfs_is_added_when_source_identity_is_resolved():
    assert safe_dfs_headline_controls(119, 134, 0) == (119, 134, True)

def test_rural_bank_only_csp_is_counted_as_an_exception_control():
    assert rural_control_group_count(358, 2) == 360

def test_rural_population_without_bank_only_controls_is_unchanged():
    assert rural_control_group_count(358, 0) == 358


def test_all_source_kpi_is_provisional_when_any_required_source_is_missing():
    status, issues = all_source_kpi_status(
        transaction_groups=10, rural_ready=True, dfs_ready=False,
        social_security_ready=True, passbook_ready=True, tab_ready=True,
    )
    assert status == 'PROVISIONAL'
    assert 'DFS' in issues

def test_all_source_kpi_ready_only_when_all_scoped_sources_are_ready():
    status, issues = all_source_kpi_status(
        transaction_groups=10, rural_ready=True, dfs_ready=True,
        social_security_ready=True, passbook_ready=True, tab_ready=True,
        loan_lead_ready=True, matm_ready=True,
    )
    assert status == 'READY'
    assert issues == []

def test_all_source_kpi_is_source_required_when_no_population_exists():
    status, issues = all_source_kpi_status(
        transaction_groups=0, rural_ready=False, dfs_ready=False,
        social_security_ready=False, passbook_ready=False, tab_ready=False,
    )
    assert status == 'SOURCE_REQUIRED'
    assert len(issues) == 8


def test_dfs_partial_identity_keeps_safe_source_controls_in_headline():
    rows = [
        {"csp_id": "1A850001", "status": "MATCHED"},
        {"csp_id": "1A850002", "status": "AMOUNT_MISMATCH"},
        {"csp_id": "1A850003", "status": "BC_ONLY_CSP"},
        {"csp_id": "", "status": "UNRESOLVED_CSP_ID"},
    ]
    assert resolved_dfs_headline_controls(rows, 1) == (1, 2, True, "PARTIAL_IDENTITY_UNRESOLVED")

def test_dfs_complete_identity_uses_full_population():
    rows = [
        {"csp_id": "1A850001", "status": "MATCHED"},
        {"csp_id": "1A850003", "status": "BC_ONLY_CSP"},
    ]
    assert resolved_dfs_headline_controls(rows, 0) == (1, 2, True, "READY")


def test_dfs_partial_identity_still_marks_all_source_kpi_provisional():
    status, issues = all_source_kpi_status(
        transaction_groups=100, rural_ready=True, dfs_ready=True,
        social_security_ready=True, passbook_ready=True, tab_ready=True,
        unresolved_identity_rows=23, unresolved_source_rows=0,
    )
    assert status == "PROVISIONAL"
    assert any("23 unresolved CSP identity" in issue for issue in issues)


def test_provisional_loan_lead_controls_are_excluded_from_headline_population():
    from app.services.control_kpi import all_source_control_kpi
    # Dashboard must pass zero loan-lead controls until the source is READY.
    matched, groups, rate = all_source_control_kpi(
        transaction_matched=80, transaction_groups=100,
        loan_lead_matched=0, loan_lead_groups=0,
    )
    assert (matched, groups, rate) == (80, 100, 80.0)

def test_all_source_status_is_provisional_until_loan_lead_amount_is_verified():
    status, issues = all_source_kpi_status(
        transaction_groups=100, rural_ready=True, dfs_ready=True,
        social_security_ready=True, passbook_ready=True, tab_ready=True,
        loan_lead_ready=False,
    )
    assert status == 'PROVISIONAL'
    assert 'Loan Lead Generation' in issues


def test_matm_controls_are_included_in_explicit_all_source_kpi():
    from app.services.control_kpi import all_source_control_kpi
    before = all_source_control_kpi(transaction_matched=60, transaction_groups=100)
    after = all_source_control_kpi(transaction_matched=60, transaction_groups=100, matm_matched=49, matm_groups=200)
    assert before == (60, 100, 60.0)
    assert after == (109, 300, 36.33)

def test_matm_source_is_required_for_all_source_kpi_ready_status():
    status, issues = all_source_kpi_status(
        transaction_groups=100, rural_ready=True, dfs_ready=True,
        social_security_ready=True, passbook_ready=True, tab_ready=True,
        loan_lead_ready=True, matm_ready=False,
    )
    assert status == 'PROVISIONAL'
    assert 'm-ATM Cash Incentive' in issues


def test_observed_combined_kpi_rate_is_count_derived_and_not_forced_to_old_baseline():
    from app.services.control_kpi import all_source_control_kpi
    matched, groups, rate = all_source_control_kpi(
        transaction_matched=3887, transaction_groups=5921
    )
    assert (matched, groups, rate) == (3887, 5921, 65.65)
    # The prior baseline 3,838 / 5,715 is 67.16%; it is a different population.
    # Adding 206 controls with only 49 new matches legitimately lowers the rate.
    assert round(3838 / 5715 * 100, 2) == 67.16
    assert round((3838 + 49) / (5715 + 206) * 100, 2) == 65.65

def test_five_star_rule_without_current_period_criteria_is_not_counted_as_matched():
    # Rule existence alone is not an eligible control; all five criteria must be
    # evidenced in a current-period CSP roster before the incentive is reconciled.
    from app.services.five_star_incentive import calculate_five_star_incentive
    result = calculate_five_star_incentive({})
    assert result.get('status') == 'EVIDENCE_REQUIRED'
    assert result.get('expected_amount') is None
