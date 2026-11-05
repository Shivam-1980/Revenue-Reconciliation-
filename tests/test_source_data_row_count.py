from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))

def test_source_data_strips_duplicate_header(monkeypatch, tmp_path):
    from app.api import source_data
    p = tmp_path / 'raw.csv'
    p.write_text('A,B\nA,B\n1,2\n', encoding='utf-8')
    monkeypatch.setitem(source_data.FILES, 'transactions', p)
    monkeypatch.setitem(source_data.FALLBACK, 'transactions', p)
    df = source_data._load('transactions')
    assert len(df) == 1
    assert df.iloc[0]['A'] == '1'

def test_header_match_ignores_bom_spaces_and_punctuation():
    from app.api import source_data
    assert source_data._looks_like_header_row(
        ['\ufeff CSP Code ', 'Transaction-Type', 'Amount'],
        ['CSP Code', 'Transaction Type', 'Amount']
    )
