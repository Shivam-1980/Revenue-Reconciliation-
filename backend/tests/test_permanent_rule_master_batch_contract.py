from app.api.reconciliation import _transaction_and_commission_batch_problem

def test_permanent_rate_master_does_not_need_a_monthly_upload_batch_id():
    tx = {"batch_id": "batch-october"}
    bc = {"batch_id": "batch-october"}
    # The rule master is intentionally not part of this batch comparison.
    assert _transaction_and_commission_batch_problem(tx, bc) is None

def test_transaction_and_bc_commission_must_be_from_same_upload_batch():
    assert _transaction_and_commission_batch_problem(
        {"batch_id": "batch-october"}, {"batch_id": "batch-september"}
    ) is not None

def test_missing_batch_id_is_not_treated_as_same_batch():
    assert _transaction_and_commission_batch_problem(
        {"batch_id": None}, {"batch_id": None}
    ) is not None


def test_reconciliation_cache_version_invalidates_older_engine_results():
    from app.services.reconciliation_cache import RECONCILIATION_ENGINE_VERSION
    assert RECONCILIATION_ENGINE_VERSION == "62.6.216-ui-security-speed"
