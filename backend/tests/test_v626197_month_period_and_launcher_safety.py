from pathlib import Path
import pandas as pd

from app.api.upload import _commission_source_period_bounds


def test_month_label_commission_period_expands_to_full_calendar_month():
    values = pd.Series(['Sep 2026', 'Sep 2026', 'Sep 2026'])
    assert _commission_source_period_bounds(values, 'month') == ('2026-09-01', '2026-09-30')


def test_multi_month_commission_period_expands_first_and_last_month():
    values = pd.Series(['Sep 2026', 'Oct 2026', 'Oct 2026'])
    assert _commission_source_period_bounds(values, 'month') == ('2026-09-01', '2026-10-31')


def test_daily_commission_period_keeps_observed_date_bounds():
    values = pd.Series(['2026-09-04', '2026-09-29'])
    assert _commission_source_period_bounds(values, 'date') == ('2026-09-04', '2026-09-29')


def test_start_launcher_checks_running_backend_before_resetting_workspace():
    root = Path(__file__).resolve().parents[2]
    launcher = (root / 'start.bat').read_text(encoding='utf-8')
    health_check = launcher.index('curl.exe -k -fsS --max-time 2 %API%/health')
    reset_call = launcher.index('reset_initial_data.py')
    reuse_branch = launcher.index('Existing Revenue Reconciliation backend matches V62.6.216; preserving current uploads and reusing it.')
    assert health_check < reset_call
    assert reuse_branch < reset_call
    assert 'goto BACKEND_READY' in launcher[reuse_branch:reset_call]
    assert 'Current workspace data has NOT been reset.' in launcher
    assert '62.6.216-ui-security-speed' in launcher
    assert 'serving a different Revenue Reconciliation version' in launcher
