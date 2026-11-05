from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def test_clean_release_does_not_bundle_an_initialization_marker():
    script = (ROOT / "backend" / "reset_initial_data.py").read_text(encoding="utf-8")
    # A release ZIP must not carry a marker from an earlier extraction/version.
    assert not (ROOT / ".eko_reconciliation_initialized_version").exists()
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)", script)
    assert match is not None
    version = match.group(1)
    assert version == "62.6.216-ui-security-speed"


def test_startup_reset_runs_after_venv_creation_and_package_install():
    bat = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert bat.index('"%PY%" reset_initial_data.py') > bat.index('pip install -r requirements.txt')
    assert "reset_initial_data.py" in bat


def test_reset_is_not_guarded_to_run_only_once_per_release():
    script = (ROOT / "backend" / "reset_initial_data.py").read_text(encoding="utf-8")
    assert "if MARKER.exists()" not in script
    assert "preserving current user uploads" not in script
    assert "on every project startup" in script


def test_startup_reset_preserves_durable_reconciliation_history():
    script = (ROOT / "backend" / "reset_initial_data.py").read_text(encoding="utf-8")
    assert "'audit': ['latest_condition_audit.csv', 'latest_condition_summary.json']" in script
    assert "run_log.csv" not in script.split("clear_patterns = {", 1)[1].split("    }", 1)[0]
    assert "reconciliation_history" not in script.split("clear_patterns = {", 1)[1].split("    }", 1)[0]
