from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / 'backend'
sys.path.insert(0, str(BACKEND))


def test_successful_transaction_source_summary_is_complete():
    from app.api.dashboard import successful_transaction_types

    payload = successful_transaction_types()
    rows = payload['rows']

    assert payload['transaction_type_count'] == len(rows)
    assert payload['total_successful_transactions'] == sum(int(r['successful_transactions']) for r in rows)
    # The release ships without any month's transactions; empty is expected until upload.
    assert payload['total_successful_transactions'] == 0
    assert payload['transaction_type_count'] == 0
