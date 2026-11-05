from pathlib import Path

from app.api.upload import _month_from_text


def test_month_parser_supports_all_months_without_year_guessing():
    labels = [
        ('Jan 2026', '2026-01'), ('Feb-2026', '2026-02'), ('Mar 2026', '2026-03'),
        ('Apr-26', '2026-04'), ('May 2026', '2026-05'), ('Jun-2026', '2026-06'),
        ('Jul 2026', '2026-07'), ('Aug-26', '2026-08'), ('Sep-2026', '2026-09'),
        ('Oct 2026', '2026-10'), ('Nov-26', '2026-11'), ('Dec 2026', '2026-12'),
    ]
    for label, expected in labels:
        assert _month_from_text(label) == expected
    assert _month_from_text('September') is None
    assert _month_from_text('') is None


def test_dfs_upload_does_not_treat_august_login_day_column_as_csp_id():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'api' / 'upload.py').read_text(encoding='utf-8')
    assert 'total_login_day_aug_26' not in source
    assert 'mtd_achievement_aug_26' not in source
    assert "'mtd_achievement','achievement','dfs_slab'" in source


def test_runtime_upload_state_is_empty_but_permanent_sbi_master_remains():
    import json
    data = Path(__file__).resolve().parents[1] / 'app' / 'data'
    meta = json.loads((data / 'upload_metadata.json').read_text(encoding='utf-8'))
    for key in ('transactions', 'commission', 'csp_geography', 'rural_csp', 'social_security_counts',
                'passbook_printing_counts', 'dfs_incentive', 'women_csp_roster', 'tab_incentive'):
        assert meta[key] is None, key
    assert meta['active_batch_id'] is None
    assert (data / 'expected_commission_rule' / 'latest.xlsx').exists()
    assert (data / 'rate_master' / 'latest_rate_master.csv').exists()
    assert not (data / 'commissions' / 'latest_commission_raw.csv').exists()
    assert not (data / 'csp_geography' / 'latest_csp_geography.csv').exists()
    assert not (data / 'supplemental' / 'latest_tab_incentive_counts.csv').exists()
    assert not (data / 'supplemental' / 'latest_tab_incentive_metadata.json').exists()


def test_month_parser_handles_three_periods_without_cross_month_aliasing():
    """August/September/October labels must resolve independently from their own values."""
    labels = {
        'Total Login Day Aug-26': '2026-08',
        'Total Login Day Sep-26': '2026-09',
        'Total Login Day Oct-26': '2026-10',
    }
    for label, expected in labels.items():
        assert _month_from_text(label) == expected
    source = (Path(__file__).resolve().parents[1] / 'app' / 'api' / 'upload.py').read_text(encoding='utf-8').lower()
    assert 'total_login_day_aug_26' not in source
    assert 'total_login_day_sep_26' not in source
    assert 'total_login_day_oct_26' not in source


def test_all_source_kpi_is_recomputed_per_period_not_accumulated():
    """Each monthly KPI is calculated from that month's controls only."""
    from app.services.control_kpi import all_source_control_kpi
    monthly = {
        '2026-08': (74, 100),
        '2026-09': (81, 100),
        '2026-10': (63, 90),
    }
    results = {}
    for period, (matched, groups) in monthly.items():
        results[period] = all_source_control_kpi(
            transaction_matched=matched, transaction_groups=groups
        )
    assert results['2026-08'] == (74, 100, 74.0)
    assert results['2026-09'] == (81, 100, 81.0)
    assert results['2026-10'] == (63, 90, 70.0)
    # Re-running a later period must not mutate an earlier period's result.
    assert results['2026-08'] == (74, 100, 74.0)


def test_prior_month_csp_aliases_are_not_applied_to_current_period_uploads():
    """Name/ID corrections from an old month must not silently mutate new uploads."""
    source = (Path(__file__).resolve().parents[1] / 'app' / 'api' / 'upload.py').read_text(encoding='utf-8')
    assert "'GURSEWAK GURSEWAK':'1A859001'" not in source
    assert "WOMEN_ALIAS_PATH" not in source
    assert not (Path(__file__).resolve().parents[1] / 'app' / 'data' / 'csp_id_aliases.csv').exists()


def test_legacy_social_security_csp_master_is_cleared_on_release_reset():
    reset = (Path(__file__).resolve().parents[1] / 'reset_initial_data.py').read_text(encoding='utf-8')
    assert "'latest_social_security_csp_master.csv'" in reset


def test_release_contains_no_prior_period_diagnostic_data_artifacts():
    """Prior August diagnostic outputs are not runtime inputs or release artifacts."""
    root = Path(__file__).resolve().parents[2]
    forbidden = [
        root / 'tools' / 'audit' / 'august_fixture_validation_summary.json',
        root / 'tools' / 'actual_source_diagnostic_v132.json',
        root / 'backend' / 'docs' / 'validation' / 'PMJJBY_PMSBY_August_2026_BC_Data_embedded_from_prior_reconciliation.csv',
    ]
    assert all(not p.exists() for p in forbidden)


def test_startup_reset_clears_all_active_sources_but_keeps_permanent_rulebooks():
    """The startup script must clear month-specific inputs on every launch."""
    reset = (Path(__file__).resolve().parents[1] / 'reset_initial_data.py').read_text(encoding='utf-8')
    for filename in (
        'latest_transactions.csv', 'latest_transactions_raw.csv',
        'latest_commission.csv', 'latest_commission_raw.csv',
        'latest_csp_geography.csv', 'latest_rural_csp_master.csv',
        'latest_social_security_counts.csv', 'latest_passbook_printing_counts.csv',
        'latest_dfs_incentive_counts.csv', 'latest_women_csp_roster.csv',
        'latest_tab_incentive_counts.csv', 'latest_matm_incentive_counts.csv',
        'latest_loan_lead_generation.csv', 'reconciliation_cache.csv',
    ):
        assert filename in reset, filename
    assert "'expected_commission_rule'" in reset
    assert "'latest.xlsx'" in reset
