from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_actual_source_validator_selects_success_sheet_explicitly():
    source = (ROOT / "tools" / "validate_actual_sources.py").read_text(encoding="utf-8")
    assert 'pd.read_excel(sys.argv[1], sheet_name="Success")' in source
    assert "except ValueError:" in source
